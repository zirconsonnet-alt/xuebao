"""AI 助手上游调用运行时。"""

from datetime import date, datetime
import traceback
from typing import Dict, List

from openai import AuthenticationError, BadRequestError, OpenAI, RateLimitError

from src.support.ai.config import AI_RUNTIME_CONFIG_PATH, AI_SECRETS_CONFIG_PATH
from src.support.ai import (
    get_llm_models_to_try,
    get_official_llm_fallback_model,
    get_official_llm_fallback_upstream_context,
    has_official_llm_fallback_upstream,
    has_upstream_for_model,
)
from src.support.ai.model_chains import AI_MODEL_CHAINS_CONFIG_PATH
from src.support.core import make_dict

from .common import (
    InvalidModelResponseError,
    _invalid_model_ids,
    _rate_limited_models,
    _stream_only_models,
    extract_completion_message,
    is_model_in_invalid_response_cooldown,
    mark_model_invalid_response,
    reset_model_invalid_response_state,
)

class AIAssistantApiRuntimeMixin:
    @staticmethod
    def _is_invalid_model_id_error(exc: BadRequestError) -> bool:
        message = str(exc).lower()
        return (
            "invalid model id" in message
            or "model not found" in message
            or "does not exist" in message
        )

    def _build_runtime_time_context(self) -> str:
        now = datetime.now().astimezone()
        weekday = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"][now.weekday()]
        offset = now.strftime("%z")
        if len(offset) == 5:
            offset = f"{offset[:3]}:{offset[3:]}"
        timezone_label = now.tzname() or offset or "本地时区"
        return (
            f"当前真实时间：{now.strftime('%Y-%m-%d %H:%M:%S')}，{weekday}，时区 {timezone_label}。\n"
            "处理“现在/今天/明天/1分钟后”等相对时间时，必须以这个时间为准。"
        )

    def _build_request_messages(self, messages=None):
        request_messages = list(messages or self.msg_list)
        runtime_message = make_dict("system", self._build_runtime_time_context())
        pending_media_message = ""
        if hasattr(self, "build_pending_media_status_message"):
            try:
                pending_media_message = self.build_pending_media_status_message()
            except Exception:
                pending_media_message = ""

        prefix_messages = [runtime_message]
        if pending_media_message:
            prefix_messages.append(make_dict("system", pending_media_message))

        if request_messages and request_messages[0].get("role") == "system":
            return [request_messages[0], *prefix_messages, *request_messages[1:]]
        return [*prefix_messages, *request_messages]

    def _log_invalid_model_response(
        self,
        model: str,
        exc: InvalidModelResponseError,
        *,
        prefix: str = "[API]",
    ) -> None:
        failure_count, entered_cooldown = mark_model_invalid_response(model)
        if entered_cooldown:
            print(
                f"{prefix} 模型 {model} 连续 {failure_count} 次返回无效响应，"
                f"已进入短期冷却: {exc.reason}"
            )
        else:
            print(
                f"{prefix} 模型 {model} 返回无效响应，"
                f"当前连续失败 {failure_count} 次: {exc.reason}"
            )
        if exc.summary:
            print(f"[API DEBUG] 模型 {model} 无效响应摘要: {exc.summary}")

    def _get_official_fallback_model(self) -> str:
        return get_official_llm_fallback_model()

    async def _call_model_once(
        self,
        *,
        model: str,
        request_messages: List[Dict[str, object]],
        context: Dict[str, object],
        tools_enable: bool,
        tarot_enable: bool,
        memes_enable: bool,
        thinking_enable: bool,
        client: OpenAI | None = None,
    ) -> str:
        request_params = {
            "model": model,
            "messages": request_messages,
            "temperature": self.temperature,
        }

        if thinking_enable:
            request_params["extra_body"] = {"enable_thinking": True}

        exclude_categories: List[str] = []
        if tools_enable:
            if not tarot_enable:
                exclude_categories.append("tarot")
            if not memes_enable:
                exclude_categories.append("memes")

            pre_route_selector = getattr(self, "_select_preferred_tool_for_user", None)
            forced_tool_caller = getattr(self, "_call_api_with_forced_tool", None)
            last_user_text_getter = getattr(self, "_get_last_user_text", None)
            if (
                not context.get("tool_gate_enforced")
                and callable(pre_route_selector)
                and callable(forced_tool_caller)
                and callable(last_user_text_getter)
            ):
                preferred_tool = pre_route_selector(
                    last_user_text_getter(),
                    exclude_categories=exclude_categories,
                )
                if preferred_tool:
                    print(f"[工具调用] 前置意图路由命中 {preferred_tool.name}")
                    forced_context = dict(context)
                    forced_context["tool_gate_enforced"] = True
                    return await forced_tool_caller(
                        model=model,
                        context=forced_context,
                        tool_name=preferred_tool.name,
                        exclude_categories=exclude_categories,
                        thinking_enable=thinking_enable,
                    )

            mcp_tools = await self._get_mcp_tools_schema_for_request(context)
            schema_context = dict(context)
            if mcp_tools:
                schema_context["mcp_tools_schema"] = mcp_tools
            tools = self._get_openai_tools_schema(
                exclude_categories=exclude_categories,
                tools_enable=tools_enable,
                context=schema_context,
            )
            if tools:
                request_params["tools"] = tools
                request_params["tool_choice"] = "auto"
                print(
                    f"[API DEBUG] 传递了 {len(tools)} 个工具: "
                    f"{[tool['function']['name'] for tool in tools]}"
                )

        client = client or self._get_client_for_model(model)
        if model in _stream_only_models:
            return await self._call_api_stream(
                request_params,
                context,
                client,
                model,
                exclude_categories,
                tools_enable,
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
                tools_enable=tools_enable,
                thinking_enable=thinking_enable,
            )

        this_reply = message.content or ""
        if tools_enable:
            gated_reply = await self._enforce_tool_gate(
                user_text=self._get_last_user_text(),
                assistant_text=this_reply,
                context=context,
                model=model,
                exclude_categories=exclude_categories,
                thinking_enable=thinking_enable,
            )
            if gated_reply is not None:
                return gated_reply
        self.add_message(make_dict("assistant", this_reply))
        return this_reply

    async def _call_official_fallback_after_invalid_response(
        self,
        *,
        failed_model: str,
        request_messages: List[Dict[str, object]],
        context: Dict[str, object],
        tools_enable: bool,
        tarot_enable: bool,
        memes_enable: bool,
    ) -> tuple[str | None, str | None]:
        fallback_model = self._get_official_fallback_model()
        if not fallback_model or fallback_model == failed_model:
            return None, None
        if not has_official_llm_fallback_upstream():
            print(f"[API] DeepSeek 官方兜底 {fallback_model} 未配置可用上游，跳过")
            return None, None

        print(f"[API] 模型 {failed_model} 连续无效响应，切换到 DeepSeek 官方兜底 {fallback_model}")
        try:
            fallback_client = get_official_llm_fallback_upstream_context(fallback_model).client
            reply = await self._call_model_once(
                model=fallback_model,
                request_messages=request_messages,
                context=context,
                tools_enable=tools_enable,
                tarot_enable=tarot_enable,
                memes_enable=memes_enable,
                thinking_enable=False,
                client=fallback_client,
            )
            return reply, None
        except InvalidModelResponseError as exc:
            self._log_invalid_model_response(fallback_model, exc)
            return None, "DeepSeek 官方兜底也未返回有效结果，请稍后再试。"
        except RateLimitError as exc:
            print(f"[API] DeepSeek 官方兜底 {fallback_model} 遇到 429 限速: {exc}")
            return None, "DeepSeek 官方兜底暂时不可用，请稍后再试。"
        except AuthenticationError as exc:
            print(f"[API] DeepSeek 官方兜底 {fallback_model} 鉴权失败: {exc}")
            return None, "DeepSeek 官方兜底鉴权失败，请检查配置。"
        except BadRequestError as exc:
            if self._is_invalid_model_id_error(exc):
                _invalid_model_ids.add(fallback_model)
            print(f"[API] DeepSeek 官方兜底 {fallback_model} 请求错误: {exc}")
            return None, "DeepSeek 官方兜底请求失败，请稍后再试。"
        except Exception as exc:
            traceback.print_exc()
            return None, f"DeepSeek 官方兜底调用失败：{exc}"

    async def _call_model_with_invalid_response_recovery(
        self,
        *,
        model: str,
        request_messages: List[Dict[str, object]],
        context: Dict[str, object],
        tools_enable: bool,
        tarot_enable: bool,
        memes_enable: bool,
        thinking_enable: bool,
    ) -> tuple[str | None, bool, str | None]:
        for attempt in range(2):
            try:
                if attempt == 1:
                    print(f"[API] 模型 {model} 上一次返回无效响应，立即重试 1 次")
                reply = await self._call_model_once(
                    model=model,
                    request_messages=request_messages,
                    context=context,
                    tools_enable=tools_enable,
                    tarot_enable=tarot_enable,
                    memes_enable=memes_enable,
                    thinking_enable=(thinking_enable and attempt == 0),
                )
                return reply, False, None
            except InvalidModelResponseError as exc:
                if attempt == 0:
                    print(f"[API] 模型 {model} 返回无效响应，准备立即重试: {exc.reason}")
                    if exc.summary:
                        print(f"[API DEBUG] 模型 {model} 无效响应摘要: {exc.summary}")
                    continue

                self._log_invalid_model_response(model, exc)
                fallback_reply, fallback_error = await self._call_official_fallback_after_invalid_response(
                    failed_model=model,
                    request_messages=request_messages,
                    context=context,
                    tools_enable=tools_enable,
                    tarot_enable=tarot_enable,
                    memes_enable=memes_enable,
                )
                if fallback_reply is not None:
                    return fallback_reply, False, None
                if fallback_error:
                    return None, False, fallback_error
                return None, False, "当前上游模型暂时未返回有效结果"

        return None, False, "当前上游模型暂时未返回有效结果"

    async def call_api(self, context: Dict[str, object] = None) -> str:
        context = context or {}
        today = date.today()
        models_to_try = get_llm_models_to_try(self.model)

        if not any(has_upstream_for_model(model_name) for model_name in models_to_try):
            return (
                "LLM 上游未配置，请先填写 AI 专属配置文件。\n"
                f"运行配置：`{AI_RUNTIME_CONFIG_PATH}`\n"
                f"密钥配置：`{AI_SECRETS_CONFIG_PATH}`\n"
                "至少需要提供以下之一：`deepseek_api_key`、`modelscope_api_key`、"
                "`anthropic_api_key` 或通用 `api_key`。"
            )

        service_config = context.get("service_config", {})
        tools_enable = service_config.get("tools_enable", self.tools_enable)
        tarot_enable = service_config.get("tarot_enable", self.tarot_enable)
        memes_enable = service_config.get("memes_enable", self.memes_enable)
        thinking_enable = service_config.get("thinking_enable", self.thinking_enable)

        self.clean_invalid_tool_calls()

        request_messages = self._build_request_messages()

        print(f"[API DEBUG] 消息数量: {len(request_messages)}")
        for index, message in enumerate(request_messages[-3:]):
            role = message.get("role", "?")
            content = message.get("content", "")
            if len(content) > 100:
                content = content[:100] + "..."
            print(f"[API DEBUG] msg[{index}] {role}: {content}")
        last_error = None

        for index, model in enumerate(models_to_try):
            if not has_upstream_for_model(model):
                print(f"[API] 模型 {model} 未找到可用上游配置，跳过")
                continue

            if model in _invalid_model_ids:
                print(f"[API] 模型 {model} 已被标记为无效模型 ID，跳过")
                continue

            if model in _rate_limited_models and _rate_limited_models[model] == today:
                print(f"[API] 模型 {model} 今日已被限速，跳过")
                continue
            if is_model_in_invalid_response_cooldown(model):
                print(f"[API] 模型 {model} 最近返回过无效响应，冷却中，跳过")
                continue

            try:
                if index > 0:
                    print(f"[API] 切换到备用模型 {model}")
                reply, stop_processing, stop_error = await self._call_model_with_invalid_response_recovery(
                    model=model,
                    request_messages=request_messages,
                    context=context,
                    tools_enable=tools_enable,
                    tarot_enable=tarot_enable,
                    memes_enable=memes_enable,
                    thinking_enable=(index == 0 and thinking_enable),
                )
                if reply is not None:
                    return reply
                last_error = stop_error or last_error
                if stop_processing:
                    if stop_error:
                        return stop_error
                    break

            except RateLimitError as exc:
                print(f"[API] 模型 {model} 遇到 429 限速，记录并跳过")
                _rate_limited_models[model] = today
                last_error = exc
                continue

            except InvalidModelResponseError as exc:
                self._log_invalid_model_response(model, exc)
                last_error = "当前上游模型暂时未返回有效结果"
                continue

            except AuthenticationError as exc:
                err_text = (
                    "鉴权失败(401)：API Key 无效或未被上游接受。\n"
                    f"请检查 AI 密钥配置文件：`{AI_SECRETS_CONFIG_PATH}`。\n"
                    "可用字段包括：\n"
                    "- ModelScope：`modelscope_api_key` / `modelscope_base_url`\n"
                    "- DeepSeek 官方：`deepseek_api_key` / `deepseek_base_url`\n"
                    "- Anthropic：`anthropic_api_key` / `anthropic_base_url`\n"
                    "- 通用兼容上游：`api_key` / `base_url`\n"
                    f"(model={model})"
                )
                print(f"[API] 模型 {model} 鉴权失败: {exc}")
                self.add_message(make_dict("assistant", err_text))
                return err_text

            except BadRequestError as exc:
                if self._is_invalid_model_id_error(exc):
                    _invalid_model_ids.add(model)
                    last_error = (
                        f"模型链配置包含无效模型 ID：{model}。"
                        f"请检查 `{AI_MODEL_CHAINS_CONFIG_PATH}`。"
                    )
                    print(f"[API] 模型 {model} 是无效模型 ID，已标记并跳过: {exc}")
                    continue
                print(f"[API] 模型 {model} 请求错误: {exc}")
                last_error = exc
                continue

            except Exception as exc:
                traceback.print_exc()
                return f"出错了：{exc}"

        if last_error == "当前上游模型暂时未返回有效结果":
            return "当前上游模型暂时未返回有效结果，请稍后再试。"
        return f"所有模型都不可用，请稍后再试：{last_error}"

    async def _call_api_stream(
        self,
        request_params: dict,
        context: Dict[str, object],
        client: OpenAI,
        model: str,
        exclude_categories: List[str],
        tools_enable: bool,
        thinking_enable: bool,
    ) -> str:
        request_params["stream"] = True
        response = client.chat.completions.create(**request_params)

        collected_content = []
        tool_calls_data = {}
        chunk_count = 0

        for chunk in response:
            chunk_count += 1
            if not chunk.choices:
                continue

            delta = chunk.choices[0].delta
            if delta.content:
                collected_content.append(delta.content)

            if delta.tool_calls:
                for tool_call in delta.tool_calls:
                    idx = tool_call.index
                    if idx not in tool_calls_data:
                        tool_calls_data[idx] = {
                            "id": tool_call.id or "",
                            "function_name": "",
                            "arguments": "",
                        }
                    if tool_call.id:
                        tool_calls_data[idx]["id"] = tool_call.id
                    if tool_call.function:
                        if tool_call.function.name:
                            tool_calls_data[idx]["function_name"] = tool_call.function.name
                        if tool_call.function.arguments:
                            tool_calls_data[idx]["arguments"] += tool_call.function.arguments

        if tool_calls_data and self.tools_enable:
            reset_model_invalid_response_state(model)
            class FakeToolCall:
                def __init__(self, tool_call_id, name, arguments):
                    self.id = tool_call_id
                    self.function = type("obj", (object,), {"name": name, "arguments": arguments})()

            class FakeMessage:
                def __init__(self, content, tool_calls):
                    self.content = content
                    self.tool_calls = tool_calls

            fake_tool_calls = [
                FakeToolCall(tc["id"], tc["function_name"], tc["arguments"])
                for tc in tool_calls_data.values()
            ]
            fake_message = FakeMessage("".join(collected_content), fake_tool_calls)
            return await self._run_tool_loop(
                first_message=fake_message,
                context=context,
                model=model,
                client=client,
                temperature=request_params.get("temperature", self.temperature),
                exclude_categories=exclude_categories,
                tools_enable=tools_enable,
                thinking_enable=thinking_enable,
            )

        this_reply = "".join(collected_content)
        if not this_reply.strip():
            raise InvalidModelResponseError(
                reason="流式响应未产生任何内容",
                response={"model": model, "chunk_count": chunk_count},
            )
        reset_model_invalid_response_state(model)
        if tools_enable:
            gated_reply = await self._enforce_tool_gate(
                user_text=self._get_last_user_text(),
                assistant_text=this_reply,
                context=context,
                model=model,
                exclude_categories=exclude_categories,
                thinking_enable=thinking_enable,
            )
            if gated_reply is not None:
                return gated_reply
        self.add_message(make_dict("assistant", this_reply))
        return this_reply


