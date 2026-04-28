"""图片生成能力上游调用辅助。"""

import asyncio
import time
import traceback
from typing import Optional

import aiohttp

from src.support.ai import config, get_image_generation_models_to_try, get_upstream_context, has_upstream_for_model


class ImageGenerationApiMixin:
    async def _generate_image_api(self, prompt: str) -> tuple[bool, str]:
        import json as json_module

        last_error = "未配置可用的画图模型"
        try:
            async with aiohttp.ClientSession() as session:
                for model_name in get_image_generation_models_to_try():
                    if not has_upstream_for_model(model_name):
                        last_error = f"模型 {model_name} 未配置可用上游"
                        continue
                    upstream = get_upstream_context(model_name)
                    headers = {
                        **upstream.headers,
                        "X-ModelScope-Async-Mode": "true",
                    }
                    request_body = json_module.dumps(
                        {
                            "model": model_name,
                            "prompt": prompt,
                        },
                        ensure_ascii=False,
                    ).encode("utf-8")
                    async with session.post(
                        f"{upstream.base_url}/images/generations",
                        headers=headers,
                        data=request_body,
                    ) as response:
                        if response.status != 200:
                            error_text = await response.text()
                            last_error = f"请求失败: {response.status} - {error_text}"
                            continue

                        result = await response.json()
                        print(f"[图片生成] 响应: {result}")
                        image_url = self._extract_image_url(result)
                        if image_url:
                            return True, image_url

                        task_id = result.get("task_id")
                        request_id = result.get("request_id")
                        if task_id:
                            success, value = await self._poll_image_generation(session, upstream.base_url, headers, task_id)
                            if success:
                                return True, value
                            last_error = value
                            continue
                        if request_id:
                            result2 = await self._fetch_task_result(
                                session,
                                upstream.base_url,
                                headers,
                                request_id,
                            )
                            if result2:
                                image_url = self._extract_image_url(result2)
                                if image_url:
                                    return True, image_url
                        last_error = f"未能获取图片: {result}"
        except Exception as exc:
            print(f"[图片生成] 失败: {exc}")
            traceback.print_exc()
            return False, f"图片生成失败: {exc}"
        return False, last_error

    async def _fetch_task_result(
        self,
        session: aiohttp.ClientSession,
        base_url: str,
        headers: dict,
        request_id: str,
    ) -> Optional[dict]:
        try:
            async with session.get(f"{base_url}/tasks/{request_id}", headers=headers) as response:
                if response.status == 200:
                    result = await response.json()
                    print(f"[图片生成] request_id 查询结果: {result}")
                    return result
        except Exception as exc:
            print(f"[图片生成] request_id 查询失败: {exc}")
        return None

    def _extract_image_url(self, result: dict) -> Optional[str]:
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
        session: aiohttp.ClientSession,
        base_url: str,
        headers: dict,
        task_id: str,
    ) -> tuple[bool, str]:
        start_time = time.time()
        poll_url = f"{base_url}/tasks/{task_id}"
        poll_headers = {
            **headers,
            "X-ModelScope-Task-Type": "image_generation",
        }

        await asyncio.sleep(1.0)
        while time.time() - start_time < config.image_gen_max_wait:
            try:
                async with session.get(poll_url, headers=poll_headers) as response:
                    result = await response.json()
                    print(f"[图片生成] 轮询响应: {result}")

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
                    await asyncio.sleep(config.image_gen_poll_interval)
            except Exception as exc:
                print(f"[图片生成] 轮询错误: {exc}")
                await asyncio.sleep(config.image_gen_poll_interval)
        return False, "图片生成超时"


__all__ = ["ImageGenerationApiMixin"]
