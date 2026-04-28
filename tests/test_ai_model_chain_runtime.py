import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import src.services._ai.api_runtime as api_runtime_module
from src.services._ai.api_runtime import AIAssistantApiRuntimeMixin
from src.services._ai.common import _invalid_model_ids


class DummyBadRequestError(Exception):
    pass


class _DummyApiAssistant(AIAssistantApiRuntimeMixin):
    def __init__(self):
        self.model = "bad-model"
        self.temperature = 0.7
        self.tools_enable = False
        self.tarot_enable = True
        self.memes_enable = False
        self.thinking_enable = False
        self.msg_list = [{"role": "user", "content": "测试一下"}]
        self.responses = {
            "good-model": "好的",
        }
        self.create_calls = {
            "bad-model": 0,
            "good-model": 0,
        }

    def clean_invalid_tool_calls(self):
        return None

    def add_message(self, record):
        self.msg_list.append(record)

    async def _get_mcp_tools_schema_for_request(self, context):
        return []

    def _get_openai_tools_schema(self, **kwargs):
        return []

    def _get_last_user_text(self) -> str:
        return "测试一下"

    async def _enforce_tool_gate(self, **kwargs):
        return None

    async def _run_tool_loop(self, **kwargs):
        raise AssertionError("本测试不应进入工具循环")

    def _get_client_for_model(self, model: str):
        assistant = self

        class DummyCompletions:
            def create(self, **kwargs):
                assistant.create_calls[model] += 1
                if model == "bad-model":
                    raise DummyBadRequestError("Error code: 400 - {'error': {'message': 'Invalid model id: bad-model'}}")
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(
                                content=assistant.responses[model],
                                tool_calls=None,
                            )
                        )
                    ]
                )

        return SimpleNamespace(chat=SimpleNamespace(completions=DummyCompletions()))


class _DummyPreRouteAssistant(AIAssistantApiRuntimeMixin):
    def __init__(self):
        self.temperature = 0.7
        self.tools_enable = True
        self.msg_list = [{"role": "user", "content": "紧急护理程序是什么"}]
        self.forced_call = None

    def _get_last_user_text(self) -> str:
        return "紧急护理程序是什么"

    def _select_preferred_tool_for_user(self, user_text: str, *, exclude_categories=None):
        return SimpleNamespace(name="query_law_docs")

    async def _call_api_with_forced_tool(
        self,
        *,
        model,
        context,
        tool_name,
        exclude_categories,
        thinking_enable,
    ):
        self.forced_call = {
            "model": model,
            "context": context,
            "tool_name": tool_name,
            "exclude_categories": exclude_categories,
            "thinking_enable": thinking_enable,
        }
        return "已强制调用工具"

    def _get_client_for_model(self, model: str):
        raise AssertionError("前置意图路由命中后不应直接请求普通模型")


def test_call_model_once_uses_pre_route_before_normal_model_call():
    assistant = _DummyPreRouteAssistant()

    reply = asyncio.run(
        assistant._call_model_once(
            model="good-model",
            request_messages=[],
            context={},
            tools_enable=True,
            tarot_enable=True,
            memes_enable=True,
            thinking_enable=False,
        )
    )

    assert reply == "已强制调用工具"
    assert assistant.forced_call["tool_name"] == "query_law_docs"
    assert assistant.forced_call["context"]["tool_gate_enforced"] is True


def test_invalid_model_id_is_marked_and_skipped_on_next_call(monkeypatch) -> None:
    assistant = _DummyApiAssistant()
    _invalid_model_ids.clear()

    monkeypatch.setattr(api_runtime_module, "BadRequestError", DummyBadRequestError)
    monkeypatch.setattr(api_runtime_module, "get_llm_models_to_try", lambda _primary=None: ["bad-model", "good-model"])
    monkeypatch.setattr(api_runtime_module, "has_upstream_for_model", lambda _model: True)

    first_reply = asyncio.run(assistant.call_api())
    second_reply = asyncio.run(assistant.call_api())

    assert first_reply == "好的"
    assert second_reply == "好的"
    assert "bad-model" in _invalid_model_ids
    assert assistant.create_calls["bad-model"] == 1
    assert assistant.create_calls["good-model"] == 2

    _invalid_model_ids.clear()


def test_invalid_model_id_error_points_to_model_chain_config(monkeypatch) -> None:
    assistant = _DummyApiAssistant()
    _invalid_model_ids.clear()

    monkeypatch.setattr(api_runtime_module, "BadRequestError", DummyBadRequestError)
    monkeypatch.setattr(api_runtime_module, "get_llm_models_to_try", lambda _primary=None: ["bad-model"])
    monkeypatch.setattr(api_runtime_module, "has_upstream_for_model", lambda _model: True)

    reply = asyncio.run(assistant.call_api())

    assert "无效模型 ID" in reply
    assert "config\\ai_model_chains.json" in reply or "config/ai_model_chains.json" in reply
    assert assistant.create_calls["bad-model"] == 1

    _invalid_model_ids.clear()
