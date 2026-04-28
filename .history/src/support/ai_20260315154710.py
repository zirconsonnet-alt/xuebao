"""AI 与视觉支撑能力。"""

import asyncio
import csv
from contextlib import asynccontextmanager
import ffmpeg
import json
import os
from abc import ABC, abstractmethod
import random
import re
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin
import uuid

import aiohttp
from bs4 import BeautifulSoup
import edge_tts
from openai import OpenAI

from .core import VisionGateway


_SEARCH_SPIDER_LOCK = asyncio.Lock()

@dataclass
class AIAssistantConfig:
    api_key: str = field(
        default_factory=lambda: (
            os.getenv("ANTHROPIC_API_KEY")
            or os.getenv("ANTHROPIC_AUTH_TOKEN")
            or os.getenv("MODEL_API_KEY")
            or os.getenv("MODELSCOPE_API_KEY")
            or os.getenv("MODELSCOPE_TOKEN")
            or os.getenv("OPENAI_API_KEY")
            or ""
        )
    )
    base_url: str = field(
        default_factory=lambda: (
            os.getenv("ANTHROPIC_BASE_URL")
            or os.getenv("MODEL_API_BASE_URL")
            or os.getenv("MODELSCOPE_API_BASE_URL")
            or os.getenv("MODELSCOPE_BASE_URL")
            or "https://api-inference.modelscope.cn/v1"
        )
    )
    model: str = "deepseek-ai/DeepSeek-V3.2"
    default_temperature: float = 1.0
    tool_max_rounds: int = 3
    tool_orchestrator: str = "langgraph"
    mcp_servers: List[Dict[str, Any]] = field(default_factory=list)
    max_msg_count: int = 40
    max_total_length: int = 32000
    max_single_msg_length: int = 4000
    default_rate_limit_per_hour: int = 3
    default_rate_limit_enabled: bool = True
    default_rate_limit_warning: str = (
        "检测到聊天功能使用频率过高，\n"
        "请注意本群以编曲作曲交流为主，\n"
        "聊天功能虽有趣，也应适当使用哦！\n"
        "如果想无限制使用功能，\n"
        "请加入雪豹小窝群：{redirect_group}"
    )
    default_redirect_group: int = 1034063784
    tts_api_url: str = os.getenv("TTS_API_URL", "http://117.50.252.57:8000")
    tts_local_service_url: str = "http://127.0.0.1:3005"
    vision_model: str = os.getenv("VISION_MODEL", "Qwen/Qwen2.5-VL-72B-Instruct")
    vision_default_prompt: str = "请简洁描述这张图片的内容，不超过100字。"
    image_gen_model: str = os.getenv("IMAGE_GEN_MODEL", "Tongyi-MAI/Z-Image-Turbo")
    image_gen_poll_interval: float = 2.0
    image_gen_max_wait: float = 120.0
    search_spider_dir: str = os.getenv("SEARCH_SPIDER_DIR", "")
    search_keywords_csv_path: str = os.getenv("SEARCH_KEYWORDS_CSV_PATH", "")
    search_result_csv_path: str = os.getenv("SEARCH_RESULT_CSV_PATH", "")
    fetch_answers_cookie: str = os.getenv("FETCH_ANSWERS_COOKIE", "")
    data_path: Path = Path("data") / "ai_assistant"
    voice_path: Path = Path("data") / "speech"
    music_path: Path = Path("data") / "bgm"

    def __post_init__(self):
        self.base_url = self._normalize_base_url(self.base_url)

        raw_tool_max_rounds = os.getenv("TOOL_MAX_ROUNDS")
        if raw_tool_max_rounds:
            try:
                value = int(raw_tool_max_rounds)
                self.tool_max_rounds = max(1, min(8, value))
            except ValueError:
                pass

        raw_tool_orchestrator = os.getenv("TOOL_ORCHESTRATOR")
        if raw_tool_orchestrator:
            value = raw_tool_orchestrator.strip().lower()
            if value in ("internal", "langgraph"):
                self.tool_orchestrator = value

        raw_mcp_servers = os.getenv("MCP_SERVERS_JSON")
        if raw_mcp_servers:
            try:
                servers = json.loads(raw_mcp_servers)
                if isinstance(servers, list):
                    self.mcp_servers = servers
            except Exception:
                pass

    @staticmethod
    def _normalize_base_url(url: str) -> str:
        if not url:
            return url
        lowered = url.lower()
        if "/v1" in lowered:
            return url.rstrip("/")
        return url.rstrip("/") + "/v1"


AVAILABLE_VOICE_IDS: Dict[str, List[Dict[str, str]]] = {
    "local": [
        {"id": "zh-CN-XiaoyiNeural", "name": "小艺（中文女声）"},
        {"id": "zh-CN-YunxiNeural", "name": "云希（中文男声）"},
        {"id": "zh-CN-XiaoxiaoNeural", "name": "晓晓（中文女声）"},
        {"id": "zh-CN-YunjianNeural", "name": "云健（中文男声）"},
        {"id": "ja-JP-NanamiNeural", "name": "七海（日语女声）"},
        {"id": "ja-JP-KeitaNeural", "name": "慧太（日语男声）"},
        {"id": "en-US-JennyNeural", "name": "Jenny（英语女声）"},
        {"id": "en-US-GuyNeural", "name": "Guy（英语男声）"},
    ],
    "tencent": [
        {"id": "lucy-voice-houge", "name": "猴哥"},
        {"id": "lucy-voice-guangdong-f1", "name": "广东女声"},
        {"id": "lucy-voice-guangxi-m1", "name": "广西男声"},
        {"id": "lucy-voice-silang", "name": "四郎"},
        {"id": "lucy-voice-f37", "name": "女声37"},
        {"id": "lucy-voice-suxinjiejie", "name": "苏心姐姐"},
    ],
    "api": [],
}


def get_voice_list_text() -> str:
    lines = ["可用语音列表：", "【本地语音】"]
    for index, voice in enumerate(AVAILABLE_VOICE_IDS["local"], 1):
        lines.append(f"  {index}. {voice['name']}")
    lines.append("【腾讯语音】")
    offset = len(AVAILABLE_VOICE_IDS["local"])
    for index, voice in enumerate(AVAILABLE_VOICE_IDS["tencent"], offset + 1):
        lines.append(f"  {index}. {voice['name']}")
    return "\n".join(lines)


def get_voice_id_by_index(index: int) -> tuple | None:
    local_count = len(AVAILABLE_VOICE_IDS["local"])
    tencent_count = len(AVAILABLE_VOICE_IDS["tencent"])

    if 1 <= index <= local_count:
        return AVAILABLE_VOICE_IDS["local"][index - 1]["id"], "local"
    if local_count < index <= local_count + tencent_count:
        return AVAILABLE_VOICE_IDS["tencent"][index - local_count - 1]["id"], "tencent"
    return None


def get_voice_type(voice_id: str) -> str:
    for tts_type, voices in AVAILABLE_VOICE_IDS.items():
        if any(voice["id"] == voice_id for voice in voices):
            return tts_type
    return "local"


config = AIAssistantConfig()


@dataclass(frozen=True)
class UpstreamContext:
    api_key: str
    base_url: str
    client: OpenAI
    headers: Dict[str, str]


def _get_modelscope_upstream() -> tuple[str, str]:
    api_key = os.getenv("MODELSCOPE_API_KEY") or os.getenv("MODELSCOPE_TOKEN") or ""
    base_url = (
        os.getenv("MODELSCOPE_API_BASE_URL")
        or os.getenv("MODELSCOPE_BASE_URL")
        or "https://api-inference.modelscope.cn/v1"
    )
    return api_key, base_url


def _get_anthropic_upstream() -> tuple[str, str]:
    api_key = os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN") or ""
    base_url = os.getenv("ANTHROPIC_BASE_URL") or ""
    return api_key, base_url


def _get_deepseek_upstream() -> tuple[str, str]:
    api_key = os.getenv("DEEPSEEK_API_KEY") or ""
    base_url = os.getenv("DEEPSEEK_API_BASE_URL") or "https://api.deepseek.com"
    return api_key, base_url


def _resolve_upstream_settings(model: str) -> tuple[str, str]:
    model = (model or "").strip()
    modelscope_key, modelscope_base = _get_modelscope_upstream()
    anthropic_key, anthropic_base = _get_anthropic_upstream()
    deepseek_key, deepseek_base = _get_deepseek_upstream()

    if "/" not in model and model.startswith("deepseek-") and deepseek_key:
        return deepseek_key, deepseek_base
    if "/" in model and modelscope_key:
        return modelscope_key, modelscope_base
    if anthropic_key and anthropic_base:
        return anthropic_key, anthropic_base
    if config.api_key and config.base_url:
        return config.api_key, config.base_url
    return "", ""


def has_upstream_for_model(model: str) -> bool:
    api_key, base_url = _resolve_upstream_settings(model)
    return bool(api_key and base_url)


def get_upstream_context(model: str) -> UpstreamContext:
    api_key, base_url = _resolve_upstream_settings(model)
    base_url = AIAssistantConfig._normalize_base_url(base_url)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    return UpstreamContext(
        api_key=api_key,
        base_url=base_url,
        client=OpenAI(api_key=api_key, base_url=base_url),
        headers=headers,
    )


def _ensure_mcp_runtime_available() -> None:
    if _MCP_IMPORT_ERROR is None:
        return
    raise RuntimeError("MCP 依赖未安装，无法启用 MCP 工具。") from _MCP_IMPORT_ERROR


def sanitize_identifier(text: str) -> str:
    if not text:
        return "x"
    sanitized = _IDENT_RE.sub("_", text.strip())
    sanitized = re.sub(r"_+", "_", sanitized).strip("_")
    return sanitized or "x"


@dataclass(frozen=True)
class McpServerConfig:
    name: str
    transport: str = "stdio"
    tool_name_mode: str = "prefixed"
    command: Optional[str] = None
    args: List[str] = field(default_factory=list)
    env: Optional[Dict[str, str]] = None
    cwd: Optional[str] = None
    encoding: str = "utf-8"
    encoding_error_handler: str = "strict"
    url: Optional[str] = None
    headers: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class McpToolSpec:
    openai_name: str
    server_name: str
    mcp_tool_name: str
    openai_schema: Dict[str, Any]


def _pick(dct: Dict[str, Any], keys: Tuple[str, ...]) -> Dict[str, Any]:
    return {key: dct[key] for key in keys if key in dct and dct[key] is not None}


def coerce_server_configs(raw: Any) -> List[McpServerConfig]:
    if not raw:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return []
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        return []

    configs: List[McpServerConfig] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        transport = str(item.get("transport") or "stdio").strip().lower()
        allowed = {"name": name, "transport": transport}
        allowed.update(
            _pick(
                item,
                (
                    "tool_name_mode",
                    "command",
                    "args",
                    "env",
                    "cwd",
                    "encoding",
                    "encoding_error_handler",
                    "url",
                    "headers",
                ),
            )
        )
        try:
            configs.append(McpServerConfig(**allowed))
        except TypeError:
            continue
    return configs


@asynccontextmanager
async def open_mcp_session(server: McpServerConfig):
    _ensure_mcp_runtime_available()
    transport = (server.transport or "stdio").lower()

    async def _yield_session(read_stream, write_stream):
        async with ClientSession(
            read_stream,
            write_stream,
            client_info=Implementation(name="xuebao", version="0.1.0"),
        ) as session:
            await session.initialize()
            yield session

    if transport == "stdio":
        if not server.command:
            raise ValueError(f"MCP server({server.name}) transport=stdio 缺少 command")
        params = StdioServerParameters(
            command=server.command,
            args=list(server.args or []),
            env=server.env,
            cwd=server.cwd,
            encoding=server.encoding or "utf-8",
            encoding_error_handler=server.encoding_error_handler or "strict",
        )
        async with stdio_client(params) as (read_stream, write_stream):
            async for session in _yield_session(read_stream, write_stream):
                yield session
        return

    if transport == "sse":
        if not server.url:
            raise ValueError(f"MCP server({server.name}) transport=sse 缺少 url")
        async with sse_client(server.url, headers=server.headers) as (read_stream, write_stream):
            async for session in _yield_session(read_stream, write_stream):
                yield session
        return

    if transport == "streamable_http":
        if not server.url:
            raise ValueError(f"MCP server({server.name}) transport=streamable_http 缺少 url")
        async with streamable_http_client(server.url) as (read_stream, write_stream, _get_session_id):
            async for session in _yield_session(read_stream, write_stream):
                yield session
        return

    if transport == "websocket":
        if not server.url:
            raise ValueError(f"MCP server({server.name}) transport=websocket 缺少 url")
        async with websocket_client(server.url) as (read_stream, write_stream):
            async for session in _yield_session(read_stream, write_stream):
                yield session
        return

    raise ValueError(f"MCP server({server.name}) 不支持 transport={server.transport}")


async def build_mcp_tooling(*, servers: List[McpServerConfig], exit_stack) -> Dict[str, Any]:
    _ensure_mcp_runtime_available()
    sessions: Dict[str, ClientSession] = {}
    tool_map: Dict[str, Dict[str, str]] = {}
    openai_tools_schema: List[Dict[str, Any]] = []

    for server in servers:
        session = await exit_stack.enter_async_context(open_mcp_session(server))
        sessions[server.name] = session
        tools_result = await session.list_tools()
        for tool in tools_result.tools or []:
            mode = (server.tool_name_mode or "prefixed").strip().lower()
            if mode == "plain":
                openai_name = tool.name
            else:
                openai_name = f"mcp_{sanitize_identifier(server.name)}__{sanitize_identifier(tool.name)}"

            if openai_name in tool_map:
                continue
            tool_map[openai_name] = {"server": server.name, "tool": tool.name}
            openai_tools_schema.append(
                {
                    "type": "function",
                    "function": {
                        "name": openai_name,
                        "description": tool.description or tool.title or openai_name,
                        "parameters": tool.inputSchema or {"type": "object", "properties": {}, "required": []},
                    },
                }
            )

    return {
        "mcp_sessions": sessions,
        "mcp_tool_map": tool_map,
        "mcp_tools_schema": openai_tools_schema,
    }


class SpeechGenerator(ABC):
    def __init__(self):
        self.voice_path = Path("data") / "speech"
        self.music_path = Path("data") / "bgm"

    @abstractmethod
    async def text_to_speech(self, text, voice_id):
        pass

    async def gen_speech(self, text, voice_id, music_enable=False):
        try:
            print("准备生成音频")
            speech_path = await self.text_to_speech(text, voice_id)
        except Exception as exc:
            print(exc)
            return None
        if music_enable:
            return await self.mix_music(speech_path)
        return speech_path

    def _new_voice_file_path(self, prefix: str, suffix: str = ".mp3") -> Path:
        self.voice_path.mkdir(parents=True, exist_ok=True)
        return self.voice_path / f"{prefix}_{uuid.uuid4().hex}{suffix}"

    @staticmethod
    def _cleanup_files(paths: List[str]) -> None:
        for raw_path in paths:
            try:
                Path(raw_path).unlink(missing_ok=True)
            except Exception:
                pass

    async def mix_music(self, speech_path):
        speech_file = Path(speech_path)
        if not self.music_path.exists():
            return str(speech_file)
        mp3_files = [file_path for file_path in self.music_path.iterdir() if file_path.is_file() and file_path.suffix.lower() == ".mp3"]
        if not mp3_files:
            return str(speech_file)

        selected_mp3_path = random.choice(mp3_files)
        merged_path = self._new_voice_file_path("merged")
        try:
            process = await asyncio.create_subprocess_exec(
                "ffmpeg",
                "-y",
                "-i",
                str(speech_file),
                "-i",
                str(selected_mp3_path),
                "-filter_complex",
                "[0:a]volume=2[a];[1:a]volume=0.1[b];[a][b]amix=inputs=2:duration=shortest",
                "-c:a",
                "mp3",
                str(merged_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await process.communicate()
        except Exception as exc:
            print(f"Error mixing music: {exc}")
            return None
        if process.returncode != 0:
            print(f"Error mixing music: {stderr.decode('utf-8', errors='ignore')}")
            return None
        return str(merged_path)


class LocalSpeechGenerator(SpeechGenerator):
    async def text_to_speech(self, text, voice_id):
        full_path = self._new_voice_file_path("speech")
        communicate = edge_tts.Communicate(text=text, voice=voice_id)
        await communicate.save(str(full_path))
        return str(full_path)


class ApiSpeechGenerator(SpeechGenerator):
    _session: aiohttp.ClientSession = None

    def __init__(self):
        super().__init__()
        self.url = config.tts_api_url

    @classmethod
    async def get_session(cls) -> aiohttp.ClientSession:
        if cls._session is None or cls._session.closed:
            cls._session = aiohttp.ClientSession()
        return cls._session

    async def text_to_speech(self, text, voice_id):
        request_id = uuid.uuid4().hex
        texts = self.split_text_to_segments(text)
        audio_files = []
        for index, segment in enumerate(texts):
            print(f"处理片段 {index + 1}/{len(texts)}: {segment}")
            audio_path = await self.call_api(segment, voice_id, index + 1, request_id=request_id)
            if audio_path:
                audio_files.append(audio_path)
        if not audio_files:
            return ""
        output_file = self._new_voice_file_path("speech")
        try:
            merged = self.merge_audio_files(audio_files, str(output_file))
        finally:
            self._cleanup_files(audio_files)
        if not merged:
            return ""
        return str(output_file)

    def _resolve_audio_download_url(self, audio_url: str) -> str:
        return urljoin(self.url.rstrip("/") + "/", audio_url)

    async def call_api(self, text: str, model_name: str, index: int, *, request_id: str) -> str:
        api_url = f"{self.url}/infer_single"
        headers = {"Content-Type": "application/json"}
        payload = {
            "text": text,
            "model_name": model_name,
            "emotion": "默认",
            "version": "v4",
            "prompt_text_lang": "中文",
            "text_lang": "中文",
            "top_k": 10,
            "top_p": 1,
            "temperature": 1,
            "text_split_method": "按标点符号切",
            "batch_size": 1,
            "batch_threshold": 0.75,
            "split_bucket": True,
            "speed_factor": 1,
            "fragment_interval": 0.3,
            "media_type": "wav",
            "parallel_infer": True,
            "repetition_penalty": 1.35,
            "seed": -1,
            "sample_steps": 32,
            "if_sr": False,
        }

        try:
            session = await self.get_session()
            async with session.post(api_url, headers=headers, data=json.dumps(payload)) as response:
                if response.status != 200:
                    error = await response.text()
                    print(f"API错误: {response.status} - {error}")
                    return ""

                result = await response.json()
                print("API响应:", result)

                if "audio_url" not in result or not result["audio_url"]:
                    print("响应中缺少音频URL")
                    return ""

                audio_url = result["audio_url"]
                download_url = self._resolve_audio_download_url(audio_url)

                async with session.get(download_url) as audio_resp:
                    if audio_resp.status != 200:
                        print(f"音频下载失败: {audio_resp.status}")
                        return ""

                    self.voice_path.mkdir(parents=True, exist_ok=True)
                    file_path = self.voice_path / f"slice_{request_id}_{index}.mp3"
                    with open(file_path, "wb") as file_obj:
                        file_obj.write(await audio_resp.read())
                    return str(file_path)
        except Exception as exc:
            print(f"API请求异常: {exc}")
            return ""

    @staticmethod
    def split_text_to_segments(text, max_length=30):
        filtered_text = re.sub(r"[^\w\s，。！？\"\"''【】《》]", "", text)
        segments = re.split(r"[，。！？]+", filtered_text)
        max_texts: List[str] = []
        current_max_text = ""
        for segment in segments:
            segment = segment.strip()
            if len(current_max_text) + len(segment) + 1 <= max_length:
                current_max_text += segment + "，"
            else:
                if current_max_text:
                    max_texts.append(current_max_text.strip("，"))
                if len(segment) > max_length:
                    max_texts.append(segment)
                current_max_text = segment + "，"
        if current_max_text:
            max_texts.append(current_max_text.strip("，"))
        return max_texts

    @staticmethod
    def merge_audio_files(audio_files: list, output_file: str) -> bool:
        try:
            inputs = [ffmpeg.input(file_path) for file_path in audio_files]
            ffmpeg.concat(*inputs, v=0, a=1).output(output_file, format="mp3").run(
                overwrite_output=True,
                quiet=True,
            )
            print(f"合并成功，输出文件：{output_file}")
            return True
        except ffmpeg.Error as exc:
            stderr = exc.stderr.decode() if exc.stderr else ""
            print("合并音频文件时出错：", stderr)
            return False


class HttpVisionGateway(VisionGateway):
    async def describe_image(self, *, image_url: str, prompt: str | None = None) -> str:
        if not prompt:
            prompt = config.vision_default_prompt

        request_body = {
            "model": config.vision_model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ],
                }
            ],
            "max_tokens": 300,
            "stream": False,
        }
        upstream = get_upstream_context(config.vision_model)
        headers = dict(upstream.headers)

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{upstream.base_url}/chat/completions",
                    headers=headers,
                    json=request_body,
                    timeout=aiohttp.ClientTimeout(total=60),
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        raise RuntimeError(f"图片识别失败: {response.status} - {error_text}")
                    result = await response.json()
                    choices = result.get("choices", [])
                    if choices:
                        message = choices[0].get("message", {})
                        content = message.get("content", "")
                        if content:
                            return content
                    return "无法识别图片内容"
        except asyncio.TimeoutError as exc:
            raise RuntimeError("图片识别超时，请稍后再试") from exc
        except Exception as exc:
            traceback.print_exc()
            raise RuntimeError(f"图片识别失败: {exc}") from exc

    async def describe_video(self, *, video_url: str, prompt: str | None = None) -> str:
        if not prompt:
            prompt = "请简洁描述这个视频的内容，包括主要人物、动作和场景，不超过150字。"

        request_body = {
            "model": config.vision_model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "video_url", "video_url": {"url": video_url}},
                    ],
                }
            ],
            "max_tokens": 500,
            "stream": False,
        }
        upstream = get_upstream_context(config.vision_model)
        headers = dict(upstream.headers)

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{upstream.base_url}/chat/completions",
                    headers=headers,
                    json=request_body,
                    timeout=aiohttp.ClientTimeout(total=60),
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        raise RuntimeError(f"视频识别失败: {response.status} - {error_text}")
                    result = await response.json()
                    choices = result.get("choices", [])
                    if choices:
                        message = choices[0].get("message", {})
                        content = message.get("content", "")
                        if content:
                            return content
                    return "无法识别视频内容"
        except asyncio.TimeoutError as exc:
            raise RuntimeError("视频识别超时，请稍后再试") from exc
        except Exception as exc:
            traceback.print_exc()
            raise RuntimeError(f"视频识别失败: {exc}") from exc

    async def generate_image(self, *, prompt: str) -> str:
        upstream = get_upstream_context(config.image_gen_model)
        headers = {**upstream.headers, "X-ModelScope-Async-Mode": "true"}
        request_body = {"model": config.image_gen_model, "prompt": prompt}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{upstream.base_url}/images/generations",
                    headers=headers,
                    json=request_body,
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        raise RuntimeError(f"请求失败: {response.status} - {error_text}")

                    result = await response.json()
                    image_url = self._extract_image_url(result)
                    if image_url:
                        return image_url

                    task_id = result.get("task_id")
                    request_id = result.get("request_id")
                    if task_id:
                        ok, url_or_err = await self._poll_image_generation(
                            session=session,
                            base_url=upstream.base_url,
                            headers=headers,
                            task_id=task_id,
                        )
                        if ok:
                            return url_or_err
                        raise RuntimeError(url_or_err)

                    if request_id:
                        result2 = await self._fetch_task_result(
                            session=session,
                            base_url=upstream.base_url,
                            headers=headers,
                            request_id=request_id,
                        )
                        if result2:
                            image_url = self._extract_image_url(result2)
                            if image_url:
                                return image_url

                    raise RuntimeError(f"未能获取图片: {result}")
        except Exception as exc:
            traceback.print_exc()
            raise RuntimeError(f"图片生成失败: {exc}") from exc

    async def _fetch_task_result(
        self,
        *,
        session: aiohttp.ClientSession,
        base_url: str,
        headers: Dict[str, Any],
        request_id: str,
    ) -> dict | None:
        try:
            async with session.get(f"{base_url}/tasks/{request_id}", headers=headers) as response:
                if response.status == 200:
                    return await response.json()
        except Exception:
            return None
        return None

    def _extract_image_url(self, result: dict) -> str | None:
        output_images = result.get("output_images")
        if isinstance(output_images, list) and output_images:
            url = output_images[0]
            if isinstance(url, str) and url:
                return url

        if "images" in result and result["images"]:
            url = result["images"][0].get("url")
            if url:
                return url

        if "data" in result and result["data"]:
            url = result["data"][0].get("url")
            if url:
                return url

        output = result.get("output", {})
        if isinstance(output, dict):
            if "data" in output and output["data"]:
                url = output["data"][0].get("url")
                if url:
                    return url
            if "results" in output and output["results"]:
                url = output["results"][0].get("url")
                if url:
                    return url
            if "image_url" in output:
                return output["image_url"]

        if "results" in result and result["results"]:
            url = result["results"][0].get("url")
            if url:
                return url

        if "image_url" in result:
            return result["image_url"]
        return None

    async def _poll_image_generation(
        self,
        *,
        session: aiohttp.ClientSession,
        base_url: str,
        headers: Dict[str, Any],
        task_id: str,
    ) -> tuple[bool, str]:
        start_time = time.time()
        poll_url = f"{base_url}/tasks/{task_id}"
        poll_headers = {**headers, "X-ModelScope-Task-Type": "image_generation"}
        await asyncio.sleep(1.0)

        while time.time() - start_time < config.image_gen_max_wait:
            try:
                async with session.get(poll_url, headers=poll_headers) as response:
                    result = await response.json()
                    errors = result.get("errors", {})
                    if isinstance(errors, dict) and errors.get("code") == 500:
                        error_msg = errors.get("message", "")
                        if "task not found" in error_msg.lower():
                            await asyncio.sleep(config.image_gen_poll_interval)
                            continue
                        return False, f"服务器错误: {error_msg}"

                    status = result.get("status") or result.get("task_status")
                    if status in ("SUCCEED", "SUCCEEDED", "SUCCESS"):
                        image_url = self._extract_image_url(result)
                        if image_url:
                            return True, image_url
                        return False, f"任务完成但未获取到图片 URL: {result}"
                    if status == "FAILED":
                        error_msg = errors.get("message") if isinstance(errors, dict) else None
                        error_msg = error_msg or result.get("message", result.get("error", "未知错误"))
                        return False, f"生成失败: {error_msg}"
                    if status in ("PENDING", "RUNNING", "QUEUED"):
                        await asyncio.sleep(config.image_gen_poll_interval)
                        continue
                    await asyncio.sleep(config.image_gen_poll_interval)
            except Exception:
                await asyncio.sleep(config.image_gen_poll_interval)

        return False, "图片生成超时"


async def run_search_spider_and_get_first_result(input_text: str) -> str:
    spiders_dir_raw = config.search_spider_dir.strip()
    if not spiders_dir_raw:
        raise RuntimeError("未配置 SEARCH_SPIDER_DIR，无法执行搜索爬虫。")

    spiders_dir = Path(spiders_dir_raw).expanduser()
    if not spiders_dir.is_absolute():
        spiders_dir = (Path.cwd() / spiders_dir).resolve()
    else:
        spiders_dir = spiders_dir.resolve()
    if not spiders_dir.exists():
        raise FileNotFoundError(f"搜索爬虫目录不存在：{spiders_dir}")
    if not spiders_dir.is_dir():
        raise NotADirectoryError(f"搜索爬虫目录不是文件夹：{spiders_dir}")

    keywords_csv_path = (
        Path(config.search_keywords_csv_path).expanduser()
        if config.search_keywords_csv_path.strip()
        else spiders_dir.parent / "key_words.csv"
    )
    csv_path = (
        Path(config.search_result_csv_path).expanduser()
        if config.search_result_csv_path.strip()
        else spiders_dir / "data_file" / "search_result_urls.csv"
    )
    if not keywords_csv_path.is_absolute():
        keywords_csv_path = (Path.cwd() / keywords_csv_path).resolve()
    else:
        keywords_csv_path = keywords_csv_path.resolve()
    if not csv_path.is_absolute():
        csv_path = (Path.cwd() / csv_path).resolve()
    else:
        csv_path = csv_path.resolve()

    keywords_csv_path.parent.mkdir(parents=True, exist_ok=True)

    async with _SEARCH_SPIDER_LOCK:
        if csv_path.exists():
            csv_path.unlink()

        with keywords_csv_path.open(mode="w", encoding="utf-8", newline="") as file_obj:
            writer = csv.writer(file_obj)
            writer.writerow([input_text])

        process = await asyncio.create_subprocess_exec(
            "scrapy",
            "crawl",
            "searchSpider",
            cwd=str(spiders_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if stdout:
            try:
                print(stdout.decode("gbk"))
            except Exception:
                print(stdout.decode(errors="ignore"))
        if stderr:
            try:
                print(stderr.decode("gbk"))
            except Exception:
                print(stderr.decode(errors="ignore"))

        if process.returncode != 0:
            raise RuntimeError("运行爬虫脚本失败")
        if not csv_path.exists():
            raise FileNotFoundError(f"CSV 文件未生成：{csv_path}")

        with csv_path.open(mode="r", encoding="utf-8") as file_obj:
            reader = csv.reader(file_obj)
            first_record: Optional[list[str]] = next(reader, None)
            if not first_record:
                raise ValueError("CSV 文件为空或没有数据")
            return first_record[0]


async def fetch_answers(url: str) -> str:
    headers = {
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }
    if config.fetch_answers_cookie:
        headers["Cookie"] = config.fetch_answers_cookie

    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url, headers=headers) as response:
            if response.status != 200:
                print(f"请求失败, 状态码: {response.status}")
                return ""
            html = await response.text()
    soup = BeautifulSoup(html, "html.parser")
    paragraphs = [p.get_text() for p in soup.find_all("p")]
    return "".join(paragraphs)


