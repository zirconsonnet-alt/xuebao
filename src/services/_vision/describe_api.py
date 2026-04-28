"""视觉描述能力上游调用辅助。"""

import asyncio
import base64
from pathlib import Path
import subprocess
import tempfile
import traceback
from typing import Optional

import aiohttp

from src.support.ai import config, get_upstream_context, get_vision_models_to_try, has_upstream_for_model
from src.services._ai.message_utils import resolve_local_media_path


class VisionDescribeApiMixin:
    @staticmethod
    def _build_local_image_data_url(image_path: Path) -> str:
        suffix = image_path.suffix.lower()
        if suffix in {".jpg", ".jpeg"}:
            mime_type = "image/jpeg"
        elif suffix == ".webp":
            mime_type = "image/webp"
        elif suffix == ".gif":
            mime_type = "image/gif"
        else:
            mime_type = "image/png"

        image_bytes = image_path.read_bytes()
        encoded = base64.b64encode(image_bytes).decode("utf-8")
        return f"data:{mime_type};base64,{encoded}"

    @staticmethod
    def _extract_video_preview_sheet(video_path: Path) -> Path:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as temp_file:
            preview_path = Path(temp_file.name)

        command = [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-vf",
            "fps=1,scale=480:-1:force_original_aspect_ratio=decrease,tile=2x2",
            "-frames:v",
            "1",
            str(preview_path),
        ]
        try:
            subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError as exc:
            if preview_path.exists():
                preview_path.unlink()
            raise RuntimeError("ffmpeg 不可用，无法从本地视频抽帧") from exc
        except subprocess.CalledProcessError as exc:
            if preview_path.exists():
                preview_path.unlink()
            stderr = (exc.stderr or "").strip()
            raise RuntimeError(f"ffmpeg 抽帧失败：{stderr or exc}") from exc

        return preview_path

    async def _describe_local_video_api(self, video_path: Path, prompt: Optional[str] = None) -> str:
        if not video_path.exists():
            return f"视频识别失败: 本地文件不存在 {video_path}"

        preview_path: Optional[Path] = None
        try:
            preview_path = self._extract_video_preview_sheet(video_path)
            preview_prompt = (
                (prompt or "请简洁描述这个视频的内容，包括主要人物、动作和场景，不超过150字。").strip()
                + "\n补充说明：输入内容是从同一视频抽取的多帧拼图，请综合这些关键帧来判断视频内容。"
            )
            return await self._describe_image_api(str(preview_path), preview_prompt)
        except Exception as exc:
            print(f"[视觉API] 本地视频识别失败: {exc}")
            traceback.print_exc()
            return f"视频识别失败: {exc}"
        finally:
            if preview_path and preview_path.exists():
                preview_path.unlink()

    async def _describe_image_api(self, image_url: str, prompt: Optional[str] = None) -> str:
        import json as json_module

        if not prompt:
            prompt = config.vision_default_prompt

        local_image_path = resolve_local_media_path(image_url)
        request_image_url = image_url
        if local_image_path is not None:
            if not local_image_path.exists():
                return f"图片识别失败: 本地文件不存在 {local_image_path}"
            request_image_url = self._build_local_image_data_url(local_image_path)

        last_error = "未配置可用的视觉模型"
        try:
            async with aiohttp.ClientSession() as session:
                for model_name in get_vision_models_to_try():
                    if not has_upstream_for_model(model_name):
                        last_error = f"模型 {model_name} 未配置可用上游"
                        continue
                    upstream = get_upstream_context(model_name)
                    headers = dict(upstream.headers)
                    request_body = json_module.dumps(
                        {
                            "model": model_name,
                            "messages": [
                                {
                                    "role": "user",
                                    "content": [
                                        {"type": "text", "text": prompt},
                                        {"type": "image_url", "image_url": {"url": request_image_url}},
                                    ],
                                }
                            ],
                            "max_tokens": 300,
                            "stream": False,
                        },
                        ensure_ascii=False,
                    ).encode("utf-8")
                    async with session.post(
                        f"{upstream.base_url}/chat/completions",
                        headers=headers,
                        data=request_body,
                    ) as response:
                        if response.status != 200:
                            error_text = await response.text()
                            last_error = f"图片识别失败: {response.status} - {error_text}"
                            continue

                        result = await response.json()
                        print(f"[视觉API] 响应: {result}")
                        choices = result.get("choices", [])
                        if choices:
                            message = choices[0].get("message", {})
                            content = message.get("content", "")
                            if content:
                                return content
                        last_error = "无法识别图片内容"
        except Exception as exc:
            print(f"[视觉API] 图片识别失败: {exc}")
            traceback.print_exc()
            return f"图片识别失败: {exc}"
        return last_error

    async def _describe_video_api(self, video_url: str, prompt: Optional[str] = None) -> str:
        import json as json_module

        if not prompt:
            prompt = "请简洁描述这个视频的内容，包括主要人物、动作和场景，不超过150字。"

        local_video_path = resolve_local_media_path(video_url)
        if local_video_path is not None:
            return await self._describe_local_video_api(local_video_path, prompt)

        last_error = "未配置可用的视觉模型"
        try:
            async with aiohttp.ClientSession() as session:
                for model_name in get_vision_models_to_try():
                    if not has_upstream_for_model(model_name):
                        last_error = f"模型 {model_name} 未配置可用上游"
                        continue
                    upstream = get_upstream_context(model_name)
                    headers = dict(upstream.headers)
                    request_body = json_module.dumps(
                        {
                            "model": model_name,
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
                        },
                        ensure_ascii=False,
                    ).encode("utf-8")
                    async with session.post(
                        f"{upstream.base_url}/chat/completions",
                        headers=headers,
                        data=request_body,
                        timeout=aiohttp.ClientTimeout(total=60),
                    ) as response:
                        if response.status != 200:
                            error_text = await response.text()
                            last_error = f"视频识别失败: {response.status} - {error_text}"
                            continue

                        result = await response.json()
                        print(f"[视觉API] 视频响应: {result}")
                        choices = result.get("choices", [])
                        if choices:
                            message = choices[0].get("message", {})
                            content = message.get("content", "")
                            if content:
                                return content
                        last_error = "无法识别视频内容"
        except asyncio.TimeoutError:
            return "视频识别超时，请稍后再试"
        except Exception as exc:
            print(f"[视觉API] 视频识别失败: {exc}")
            traceback.print_exc()
            return f"视频识别失败: {exc}"
        return last_error


__all__ = ["VisionDescribeApiMixin"]
