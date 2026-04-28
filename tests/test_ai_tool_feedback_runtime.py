import asyncio
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.services._ai.tool_execution import ToolExecutionMixin


class DummyToolFeedbackRuntime(ToolExecutionMixin):
    def __init__(self):
        self.sent_messages = []

    async def send_text(self, message: str):
        self.sent_messages.append(message)


def test_tool_feedback_silences_all_success_results() -> None:
    runtime = DummyToolFeedbackRuntime()

    asyncio.run(
        runtime._send_tool_feedback(
            [
                {"name": "generate_image", "success": True, "message": "图片已生成并发送"},
                {"name": "draw_tarot_card", "success": True, "message": "已为用户抽取塔罗牌并发送"},
                {"name": "some_tool", "success": True, "message": "执行成功"},
            ]
        )
    )

    assert runtime.sent_messages == []


def test_tool_feedback_merges_failure_results_into_one_message() -> None:
    runtime = DummyToolFeedbackRuntime()

    asyncio.run(
        runtime._send_tool_feedback(
            [
                {"name": "success_tool", "success": True, "message": "执行成功"},
                {"name": "first_tool", "success": False, "message": "第一个错误"},
                {"name": "second_tool", "success": False, "message": "第二个错误" * 20},
            ]
        )
    )

    assert len(runtime.sent_messages) == 1
    assert runtime.sent_messages[0].startswith("工具执行遇到问题：")
    assert "first_tool: 第一个错误" in runtime.sent_messages[0]
    assert "second_tool: " in runtime.sent_messages[0]
    assert runtime.sent_messages[0].endswith("...")
