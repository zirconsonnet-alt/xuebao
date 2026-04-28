"""AI 工具结果渲染辅助。"""

import json
from typing import Any, Dict, List


class ToolResultRenderMixin:
    _VISIBLE_SUCCESS_SUMMARY_TOOLS = set()
    _VISIBLE_SUCCESS_FEEDBACK_TOOLS = set()
    _SUCCESS_FEEDBACK_MESSAGES = {
        "generate_image": "图片已生成并发送",
        "draw_tarot_card": "已为用户抽取塔罗牌并发送",
        "tarot_fortune": "已为用户发送今日运势",
        "tarot_reading": "已发送塔罗牌详细解读",
    }

    def _truncate_text(self, text: str, max_len: int) -> str:
        if not text:
            return ""
        if len(text) <= max_len:
            return text
        return text[: max_len - 1] + "…"

    def _format_tool_data_for_user(self, data: Any) -> str:
        if data is None:
            return ""

        if isinstance(data, dict):
            if not data:
                return ""
            lines = []
            for key, value in data.items():
                if isinstance(value, (dict, list, tuple)):
                    value_text = self._truncate_text(json.dumps(value, ensure_ascii=False), 800)
                else:
                    value_text = str(value)
                lines.append(f"{key}：{value_text}")
            return "\n".join(lines)

        try:
            return self._truncate_text(json.dumps(data, ensure_ascii=False, indent=2), 1200)
        except Exception:
            return self._truncate_text(str(data), 1200)

    def _is_default_tool_data(self, *, tool_name: str, data: Any) -> bool:
        if not isinstance(data, dict):
            return False
        return set(data.keys()) == {"tool", "args"} and data.get("tool") == tool_name

    def _get_default_success_feedback(self, *, tool_name: str) -> str | None:
        return self._SUCCESS_FEEDBACK_MESSAGES.get(tool_name)

    def _should_hide_tool_summary(self, *, tool_name: str, result: Dict[str, Any]) -> bool:
        if not result.get("success", False):
            return False
        return tool_name not in self._VISIBLE_SUCCESS_SUMMARY_TOOLS

    def _should_send_tool_feedback(self, *, tool_name: str, result: Dict[str, Any]) -> bool:
        if not result.get("success", False):
            return True
        return tool_name in self._VISIBLE_SUCCESS_FEEDBACK_TOOLS

    def _render_tool_result_for_user(self, *, tool_name: str, result: Dict[str, Any]) -> str:
        success = bool(result.get("success", False))
        message = result.get("message") or ""
        data = result.get("data")

        if not success:
            if message:
                return f"【{tool_name}】失败：{message}"
            return f"【{tool_name}】失败"

        if self._should_hide_tool_summary(tool_name=tool_name, result=result):
            return ""

        data_text = ""
        if data is not None and not self._is_default_tool_data(tool_name=tool_name, data=data):
            data_text = self._format_tool_data_for_user(data)

        if data_text and message and message != "执行成功":
            return f"【{tool_name}】\n{data_text}\n\n说明：{message}"
        if data_text:
            return f"【{tool_name}】\n{data_text}"
        if message:
            return f"【{tool_name}】{message}"
        return f"【{tool_name}】执行成功"

    def _normalize_mcp_call_tool_result(self, call_result: Any) -> Dict[str, Any]:
        try:
            payload = call_result.model_dump()
        except Exception:
            payload = {"raw": str(call_result)}

        structured = payload.get("structuredContent")
        if isinstance(structured, dict) and "success" in structured:
            if "data" not in structured:
                structured["data"] = None
            if "message" not in structured:
                structured["message"] = ""
            return structured

        content_blocks = payload.get("content") or []
        texts: List[str] = []
        for block in content_blocks:
            if isinstance(block, dict) and isinstance(block.get("text"), str) and block.get("text"):
                texts.append(block["text"])

        data: Dict[str, Any] = {}
        text = "\n".join(texts).strip()
        if text:
            data["text"] = text
        if payload.get("structuredContent") is not None:
            data["structuredContent"] = payload.get("structuredContent")
        if payload.get("meta") is not None:
            data["meta"] = payload.get("meta")

        is_error = bool(payload.get("isError"))
        message = text or "MCP 工具执行失败" if is_error else "执行成功"
        return {"success": (not is_error), "message": message, "data": data}


__all__ = ["ToolResultRenderMixin"]
