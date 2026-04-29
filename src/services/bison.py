"""
nonebot_bison 的 services owner facade。

`src.vendors.nonebot_bison` 只保留无副作用的包元信息；
真正的依赖声明、vendor alias 绑定与运行时激活统一由本文件以显式 facade 形式代管。
"""

import asyncio
import importlib
import json
import re
import sys
from pathlib import Path
from threading import RLock
from types import ModuleType
from typing import Any, cast

import httpx
from nonebot import get_bot, require
from nonebot.log import logger
from nonebot.plugin import get_plugin, load_plugin

from src.support.cache_cleanup import cleanup_bison_music_card_cache
from src.support.core import Services, ai_tool
from src.support.group import run_flow, wait_for
from src.support.storage_guard import ensure_optional_write_allowed
from .base import BaseService, config_property, service_action


BISON_VENDOR_PACKAGE = "src.vendors.nonebot_bison"
BISON_VENDOR_ALIAS = "nonebot_bison"

BISON_DEPENDENCY_PLUGINS: tuple[str, ...] = (
    "nonebot_plugin_apscheduler",
    "nonebot_plugin_datastore",
    "nonebot_plugin_saa",
)

# 基础支撑模块：为后续注册入口提供 import 路径与运行上下文。
BISON_SUPPORT_MODULES: tuple[str, ...] = (
    "config",
    "types",
    "utils",
    "post",
    "theme",
    "platform",
    "send",
    "scheduler",
)

# 明确承担注册/启动职责的入口模块。
BISON_ENTRY_MODULES: tuple[str, ...] = (
    "bootstrap",
    "admin_page",
    "sub_manager",
)

#
# `config` 与承担注册职责的入口模块依赖插件调用者上下文；
# 其余支撑模块优先走 `nonebot_bison.*`，避免 vendor 路径与别名路径双重导入。
BISON_VENDOR_CONTEXT_MODULES: tuple[str, ...] = (
    "config",
    "bootstrap",
    "admin_page",
    "sub_manager",
)

_RUNTIME_ACTIVATED = False
_RUNTIME_PATCHED = False
_BISON_STATE_FILE_LOCK = RLock()

BISON_DELIVERY_STATE_PATH = Path("data") / "bison_delivery_state.json"
BISON_BOOTSTRAP_BACKFILL_HOURS = 24
BISON_BOOTSTRAP_BACKFILL_LIMIT = 1
BISON_RECENT_POST_CACHE_LIMIT = 200
BISON_DEFAULT_SCHEDULE_WEIGHT = 10
BISON_MUSIC_CARD_CACHE_DIR = Path("data") / "bison_music_card"
BISON_MUSIC_CARD_AUDIO_DIR = BISON_MUSIC_CARD_CACHE_DIR / "audio"
BISON_MUSIC_CARD_TEMP_DIR = BISON_MUSIC_CARD_CACHE_DIR / "temp"
BISON_DEFAULT_MUSIC_CARD_CACHE_GROUP_ID = 750932711
BISON_MUSIC_CARD_MAX_DURATION_SECONDS = 10 * 60
BISON_MUSIC_CARD_UPLOAD_RETRIES = 6
BISON_MUSIC_CARD_UPLOAD_WAIT_SECONDS = 0.5
BISON_MUSIC_CARD_FALLBACK_VOICE_ID = "zh-CN-XiaoyiNeural"
BISON_BILIBILI_STREAM_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.bilibili.com/",
}

_BISON_AUDIO_FILE_LOCKS: dict[str, asyncio.Lock] = {}
_BISON_AUDIO_UPLOAD_LOCKS: dict[str, asyncio.Lock] = {}


def _normalize_bison_seen_state(raw_state: Any) -> dict[str, Any]:
    recent_post_ids = []
    exists_posts = []
    if isinstance(raw_state, dict):
        recent_post_ids = list(raw_state.get("recent_post_ids") or [])
        exists_posts = list(raw_state.get("exists_posts") or [])
        inited = bool(raw_state.get("inited", False))
        last_seen_at = raw_state.get("last_seen_at")
    else:
        recent_post_ids = list(getattr(raw_state, "recent_post_ids", []) or [])
        exists_posts = list(getattr(raw_state, "exists_posts", []) or [])
        inited = bool(getattr(raw_state, "inited", False))
        last_seen_at = getattr(raw_state, "last_seen_at", None)

    merged_ids: list[str] = []
    seen_ids = set()
    for post_id in [*recent_post_ids, *exists_posts]:
        normalized_post_id = str(post_id)
        if normalized_post_id in seen_ids:
            continue
        merged_ids.append(normalized_post_id)
        seen_ids.add(normalized_post_id)
        if len(merged_ids) >= BISON_RECENT_POST_CACHE_LIMIT:
            break

    if last_seen_at is not None:
        try:
            last_seen_at = int(last_seen_at)
        except (TypeError, ValueError):
            last_seen_at = None

    return {
        "inited": inited,
        "last_seen_at": last_seen_at,
        "recent_post_ids": merged_ids,
    }


def _read_bison_delivery_state() -> dict[str, dict[str, Any]]:
    with _BISON_STATE_FILE_LOCK:
        if not BISON_DELIVERY_STATE_PATH.exists():
            return {}
        try:
            payload = json.loads(BISON_DELIVERY_STATE_PATH.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning(f"读取 Bison 投递状态失败：{exc}")
            return {}
    if not isinstance(payload, dict):
        return {}
    return {
        str(target_key): _normalize_bison_seen_state(target_state)
        for target_key, target_state in payload.items()
    }


def _write_bison_delivery_state(state: dict[str, dict[str, Any]]) -> None:
    with _BISON_STATE_FILE_LOCK:
        try:
            BISON_DELIVERY_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            BISON_DELIVERY_STATE_PATH.write_text(
                json.dumps(state, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning(f"写入 Bison 投递状态失败：{exc}")


def _get_bison_target_state_key(platform_name: str, target: Any) -> str:
    return f"{platform_name}:{target}"


def _load_bison_target_state(*, platform_name: str, target: Any, cached_state: Any = None) -> dict[str, Any]:
    if cached_state is not None:
        return _normalize_bison_seen_state(cached_state)

    state = _read_bison_delivery_state()
    return _normalize_bison_seen_state(state.get(_get_bison_target_state_key(platform_name, target)))


def _save_bison_target_state(*, platform_name: str, target: Any, state: dict[str, Any]) -> None:
    all_state = _read_bison_delivery_state()
    all_state[_get_bison_target_state_key(platform_name, target)] = _normalize_bison_seen_state(state)
    _write_bison_delivery_state(all_state)


def _track_bison_seen_posts(platform_obj: Any, state: dict[str, Any], raw_post_list: list[Any]) -> None:
    tracked_ids: list[str] = []
    last_seen_at = state.get("last_seen_at")
    if last_seen_at is not None:
        try:
            last_seen_at = int(last_seen_at)
        except (TypeError, ValueError):
            last_seen_at = None

    for raw_post in raw_post_list:
        tracked_ids.append(str(platform_obj.get_id(raw_post)))
        post_time = platform_obj.get_date(raw_post)
        if post_time is None:
            continue
        try:
            post_time = int(post_time)
        except (TypeError, ValueError):
            continue
        last_seen_at = post_time if last_seen_at is None else max(last_seen_at, post_time)

    merged_ids: list[str] = []
    seen_ids = set()
    for post_id in tracked_ids + list(state.get("recent_post_ids") or []):
        normalized_post_id = str(post_id)
        if normalized_post_id in seen_ids:
            continue
        merged_ids.append(normalized_post_id)
        seen_ids.add(normalized_post_id)
        if len(merged_ids) >= BISON_RECENT_POST_CACHE_LIMIT:
            break

    state["recent_post_ids"] = merged_ids
    state["last_seen_at"] = last_seen_at


def _is_bison_seen_post(platform_obj: Any, state: dict[str, Any], raw_post: Any) -> bool:
    post_id = str(platform_obj.get_id(raw_post))
    if post_id in set(state.get("recent_post_ids") or []):
        return True

    last_seen_at = state.get("last_seen_at")
    if last_seen_at is None:
        return False
    post_time = platform_obj.get_date(raw_post)
    if post_time is None:
        return False
    try:
        return int(post_time) < int(last_seen_at)
    except (TypeError, ValueError):
        return False


def _filter_bison_posts_for_service(platform_obj: Any, raw_post_list: list[Any]) -> list[Any]:
    platform_module = importlib.import_module("nonebot_bison.platform.platform")
    category_not_support = platform_module.CategoryNotSupport
    category_not_recognize = platform_module.CategoryNotRecognize

    filtered_posts = []
    for raw_post in raw_post_list:
        try:
            platform_obj.get_category(raw_post)
        except category_not_support as exc:
            logger.info("未支持解析的推文类别：" + repr(exc) + "，忽略")
            continue
        except category_not_recognize as exc:
            logger.warning("未知推文类别：" + repr(exc))
            for message in platform_obj.ctx.gen_req_records():
                logger.warning(message)
            continue
        except NotImplementedError:
            pass
        filtered_posts.append(raw_post)
    return filtered_posts


def _select_bison_bootstrap_posts(platform_obj: Any, filtered_post: list[Any], plugin_config_obj: Any) -> list[Any]:
    backfill_hours = max(
        0,
        int(getattr(plugin_config_obj, "bison_bootstrap_backfill_hours", BISON_BOOTSTRAP_BACKFILL_HOURS)),
    )
    backfill_limit = max(
        0,
        int(getattr(plugin_config_obj, "bison_bootstrap_backfill_limit", BISON_BOOTSTRAP_BACKFILL_LIMIT)),
    )
    if backfill_hours == 0 or backfill_limit == 0:
        return []

    now_ts = int(importlib.import_module("time").time())
    window_seconds = backfill_hours * 60 * 60
    recent_posts = []
    for raw_post in filtered_post:
        post_time = platform_obj.get_date(raw_post)
        if post_time is None:
            continue
        try:
            post_time = int(post_time)
        except (TypeError, ValueError):
            continue
        if now_ts - post_time > window_seconds:
            continue
        recent_posts.append(raw_post)
        if len(recent_posts) >= backfill_limit:
            break
    return recent_posts


def _get_bison_schedulable_weight(cur_weight: dict[str, int], schedulable: Any) -> int:
    target_key = f"{schedulable.platform_name}-{schedulable.target}"
    if target_key in cur_weight:
        return int(cur_weight[target_key])

    logger.warning(
        f"Bison 调度权重缺失，使用默认值 {BISON_DEFAULT_SCHEDULE_WEIGHT}：{target_key}"
    )
    return BISON_DEFAULT_SCHEDULE_WEIGHT


def _get_bison_async_lock(lock_store: dict[str, asyncio.Lock], key: str) -> asyncio.Lock:
    lock = lock_store.get(key)
    if lock is None:
        lock = asyncio.Lock()
        lock_store[key] = lock
    return lock


def _select_bison_posts_for_delivery(platform_name: str, send_list: list[Any]) -> list[Any]:
    if platform_name != "bilibili":
        return list(send_list)

    video_posts = [post for post in send_list if _get_bison_music_card_meta(post)]
    if not video_posts:
        if send_list:
            logger.info(
                f"Bison B站本次待投递 {len(send_list)} 条，"
                "过滤音乐卡片视频后无可发送内容"
            )
        return []

    if len(video_posts) <= 1:
        if len(video_posts) != len(send_list):
            logger.info(
                f"Bison B站本次待投递 {len(send_list)} 条，"
                f"仅保留 {len(video_posts)} 条音乐卡片视频"
            )
        return list(video_posts)

    def sort_key(indexed_post: tuple[int, Any]) -> tuple[float, int]:
        index, post = indexed_post
        try:
            timestamp = float(getattr(post, "timestamp", 0) or 0)
        except (TypeError, ValueError):
            timestamp = 0.0
        return timestamp, -index

    latest_index, latest_post = max(enumerate(video_posts), key=sort_key)
    logger.info(
        f"Bison B站本次待投递 {len(send_list)} 条，"
        f"过滤后保留 {len(video_posts)} 条音乐卡片视频，"
        f"仅发送最新一条：index={latest_index} timestamp={getattr(latest_post, 'timestamp', None)}"
    )
    return [latest_post]


def _is_bison_bilibili_video_post(post: Any) -> bool:
    platform = getattr(post, "platform", None)
    platform_name = str(getattr(platform, "platform_name", "") or "")
    post_url = str(getattr(post, "url", "") or "")
    return platform_name == "bilibili" and "/video/" in post_url


def _get_bison_music_card_meta(post: Any) -> dict[str, str] | None:
    raw_meta = getattr(post, "_bison_music_card_meta", None)
    if not isinstance(raw_meta, dict):
        return None

    url = str(raw_meta.get("url") or "").strip()
    cover = str(raw_meta.get("cover") or "").strip()
    title = str(raw_meta.get("title") or "").strip()
    singer = str(raw_meta.get("singer") or "").strip()
    if not url or not cover or not title:
        return None
    return {
        "url": url,
        "cover": cover,
        "title": title,
        "singer": singer,
    }


def _attach_bison_music_card_meta(post: Any) -> None:
    post_url = str(getattr(post, "url", "") or "").strip()
    if "/video/" not in post_url:
        return

    images = getattr(post, "images", None) or []
    cover = images[0] if images else None
    if not isinstance(cover, str) or not cover.strip():
        return

    title = str(getattr(post, "title", "") or getattr(post, "content", "") or "B站视频").strip()
    if not title:
        title = "B站视频"

    singer = str(getattr(post, "nickname", "") or "Bilibili").strip()
    setattr(
        post,
        "_bison_music_card_meta",
        {
            "url": post_url,
            "cover": cover.strip(),
            "title": title,
            "singer": singer,
        },
    )


def _parse_bison_bilibili_video_url(video_url: str) -> tuple[str, str, int] | None:
    page_match = re.search(r"(?:\?|&)p=(\d{1,3})", video_url)
    page_index = max(int(page_match.group(1)) - 1, 0) if page_match else 0

    if bvid_match := re.search(r"/video/(BV[0-9A-Za-z]{10})", video_url, flags=re.IGNORECASE):
        return "bvid", bvid_match.group(1), page_index
    if aid_match := re.search(r"/video/av(\d+)", video_url, flags=re.IGNORECASE):
        return "aid", aid_match.group(1), page_index
    return None


def _get_bison_music_cache_key(video_url: str) -> str | None:
    parsed = _parse_bison_bilibili_video_url(video_url)
    if not parsed:
        return None
    video_kind, video_id, page_index = parsed
    normalized_video_id = video_id.lower() if video_kind == "bvid" else video_id
    return f"{video_kind}_{normalized_video_id}_p{page_index}"


async def _download_bison_file(url: str, save_path: Path, headers: dict[str, str] | None = None) -> Path | None:
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=120.0) as client:
            async with client.stream("GET", url, headers=headers) as response:
                response.raise_for_status()
                try:
                    expected_bytes = int(response.headers.get("content-length", "0") or 0)
                except ValueError:
                    expected_bytes = 0
                decision = ensure_optional_write_allowed(
                    "Bison 音频下载缓存写入",
                    save_path,
                    expected_bytes=expected_bytes or None,
                )
                if not decision.allowed:
                    logger.warning(decision.message)
                    return None
                save_path.parent.mkdir(parents=True, exist_ok=True)
                with save_path.open("wb") as file_obj:
                    async for chunk in response.aiter_bytes():
                        file_obj.write(chunk)
        return save_path
    except Exception as exc:
        logger.warning(f"Bison 音频流下载失败：{url} {exc}")
        return None


async def _convert_bison_audio_to_mp3(source_path: Path, target_path: Path) -> Path | None:
    if not source_path.exists():
        return None

    try:
        expected_bytes = source_path.stat().st_size
    except OSError:
        expected_bytes = None
    decision = ensure_optional_write_allowed(
        "Bison 音频转码缓存写入",
        target_path,
        expected_bytes=expected_bytes,
    )
    if not decision.allowed:
        logger.warning(decision.message)
        return None

    target_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        process = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-y",
            "-i",
            str(source_path),
            "-vn",
            "-acodec",
            "libmp3lame",
            "-ab",
            "192k",
            str(target_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        logger.warning(f"Bison 音频转码失败，未找到 ffmpeg：{exc}")
        return None

    _, stderr = await process.communicate()
    if process.returncode != 0:
        stderr_text = stderr.decode("utf-8", errors="ignore")
        logger.warning(f"Bison 音频转码失败：{stderr_text[-300:]}")
        return None
    return target_path if target_path.exists() else None


async def _ensure_bison_music_audio_file(video_url: str) -> tuple[Path | None, str | None]:
    parsed = _parse_bison_bilibili_video_url(video_url)
    cache_key = _get_bison_music_cache_key(video_url)
    if not parsed or not cache_key:
        return None, None

    target_mp3_path = BISON_MUSIC_CARD_AUDIO_DIR / f"{cache_key}.mp3"
    if target_mp3_path.exists():
        cleanup_bison_music_card_cache(protected_paths=[target_mp3_path])
        return target_mp3_path, cache_key

    lock = _get_bison_async_lock(_BISON_AUDIO_FILE_LOCKS, cache_key)
    async with lock:
        if target_mp3_path.exists():
            cleanup_bison_music_card_cache(protected_paths=[target_mp3_path])
            return target_mp3_path, cache_key

        video_kind, video_id, page_index = parsed
        try:
            bilibili_api_module = importlib.import_module("bilibili_api")
            video_module = importlib.import_module("bilibili_api.video")
            credential = bilibili_api_module.Credential()
            video_obj = (
                video_module.Video(bvid=video_id, credential=credential)
                if video_kind == "bvid"
                else video_module.Video(aid=int(video_id), credential=credential)
            )
        except Exception as exc:
            logger.warning(f"Bison 初始化 B 站音频下载器失败：{video_url} {exc}")
            return None, cache_key

        try:
            video_info = await video_obj.get_info()
        except Exception as exc:
            logger.warning(f"Bison 获取 B 站视频信息失败：{video_url} {exc}")
            return None, cache_key

        duration = int(video_info.get("duration") or 0)
        if pages := video_info.get("pages"):
            if 0 <= page_index < len(pages):
                duration = int(pages[page_index].get("duration") or duration)
        if duration > BISON_MUSIC_CARD_MAX_DURATION_SECONDS:
            logger.info(
                f"Bison 视频时长 {duration}s 超过音乐卡片上限 {BISON_MUSIC_CARD_MAX_DURATION_SECONDS}s，跳过音频卡片：{video_url}"
            )
            return None, cache_key

        try:
            download_url_data = await video_obj.get_download_url(page_index=page_index)
            detector = video_module.VideoDownloadURLDataDetecter(download_url_data)
            streams = detector.detect_best_streams()
        except Exception as exc:
            logger.warning(f"Bison 获取 B 站音频流失败：{video_url} {exc}")
            return None, cache_key

        audio_stream = next((stream for stream in streams if stream and "AudioStream" in type(stream).__name__), None)
        if audio_stream is None and len(streams) > 1:
            audio_stream = streams[1]
        audio_url = getattr(audio_stream, "url", None)
        if not audio_url:
            logger.warning(f"Bison 未找到可用音频流，准备改用提示语音：{video_url}")
            return None, cache_key

        temp_audio_path = BISON_MUSIC_CARD_TEMP_DIR / f"{cache_key}.m4s"
        downloaded_path = await _download_bison_file(str(audio_url), temp_audio_path, BISON_BILIBILI_STREAM_HEADERS)
        if not downloaded_path:
            temp_audio_path.unlink(missing_ok=True)
            return None, cache_key

        converted_path = await _convert_bison_audio_to_mp3(downloaded_path, target_mp3_path)
        temp_audio_path.unlink(missing_ok=True)
        if not converted_path:
            target_mp3_path.unlink(missing_ok=True)
            return None, cache_key
        cleanup_bison_music_card_cache(protected_paths=[converted_path])
        return converted_path, cache_key


def _extract_bison_group_files(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        files = payload.get("files")
        if isinstance(files, list):
            return [item for item in files if isinstance(item, dict)]
        data = payload.get("data")
        if isinstance(data, dict) and isinstance(data.get("files"), list):
            return [item for item in data["files"] if isinstance(item, dict)]
    return []


async def _find_bison_group_file(bot: Any, group_id: int, file_name: str) -> dict[str, Any] | None:
    try:
        payload = await bot.get_group_root_files(group_id=group_id)
    except Exception as exc:
        logger.warning(f"Bison 查询群文件失败：group={group_id} {exc}")
        return None

    for file_entry in _extract_bison_group_files(payload):
        if str(file_entry.get("file_name") or "") == file_name:
            return file_entry
    return None


async def _resolve_bison_group_file_url(bot: Any, group_id: int, file_entry: dict[str, Any]) -> str | None:
    try:
        payload = await bot.get_group_file_url(
            group_id=group_id,
            file_id=str(file_entry["file_id"]),
            busid=int(file_entry["busid"]),
        )
    except Exception as exc:
        logger.warning(f"Bison 获取群文件外链失败：group={group_id} {exc}")
        return None

    if isinstance(payload, dict):
        direct_url = payload.get("url")
        if isinstance(direct_url, str) and direct_url:
            return direct_url
        data = payload.get("data")
        if isinstance(data, dict):
            nested_url = data.get("url")
            if isinstance(nested_url, str) and nested_url:
                return nested_url
    return None


async def _get_or_upload_bison_audio_url(group_id: int, audio_path: Path, cache_key: str) -> str | None:
    upload_key = f"{group_id}:{cache_key}"
    lock = _get_bison_async_lock(_BISON_AUDIO_UPLOAD_LOCKS, upload_key)
    file_name = f"bison_{cache_key}.mp3"

    async with lock:
        try:
            bot = get_bot()
        except Exception as exc:
            logger.warning(f"Bison 获取 Bot 失败，无法上传音频卡片资源：{exc}")
            return None

        existing_file = await _find_bison_group_file(bot, group_id, file_name)
        if existing_file:
            return await _resolve_bison_group_file_url(bot, group_id, existing_file)

        try:
            await bot.upload_group_file(
                group_id=group_id,
                file=str(audio_path.resolve()),
                name=file_name,
            )
        except Exception as exc:
            logger.warning(f"Bison 上传音频到群文件失败：group={group_id} {exc}")
            return None

        for _ in range(BISON_MUSIC_CARD_UPLOAD_RETRIES):
            await asyncio.sleep(BISON_MUSIC_CARD_UPLOAD_WAIT_SECONDS)
            uploaded_file = await _find_bison_group_file(bot, group_id, file_name)
            if not uploaded_file:
                continue
            if file_url := await _resolve_bison_group_file_url(bot, group_id, uploaded_file):
                return file_url

        logger.warning(f"Bison 上传音频后未找到可用外链：group={group_id} file={file_name}")
        return None


def _build_bison_music_card_fallback_text(title: str) -> str:
    normalized_title = " ".join(str(title or "").split())
    if len(normalized_title) > 32:
        normalized_title = normalized_title[:32] + "..."
    if normalized_title:
        return f"B站有新视频：{normalized_title}。音频暂时无法获取，请点开卡片查看原视频。"
    return "B站有新视频，音频暂时无法获取，请点开卡片查看原视频。"


async def _ensure_bison_music_fallback_audio_file(cache_key: str, title: str) -> tuple[Path | None, str | None]:
    if not cache_key:
        return None, None

    fallback_cache_key = f"tts_{cache_key}"
    target_mp3_path = BISON_MUSIC_CARD_AUDIO_DIR / f"{fallback_cache_key}.mp3"
    if target_mp3_path.exists():
        cleanup_bison_music_card_cache(protected_paths=[target_mp3_path])
        return target_mp3_path, fallback_cache_key

    lock = _get_bison_async_lock(_BISON_AUDIO_FILE_LOCKS, fallback_cache_key)
    async with lock:
        if target_mp3_path.exists():
            cleanup_bison_music_card_cache(protected_paths=[target_mp3_path])
            return target_mp3_path, fallback_cache_key

        try:
            from src.support.ai import LocalSpeechGenerator

            generator = LocalSpeechGenerator()
            generator.voice_path = BISON_MUSIC_CARD_TEMP_DIR
            generated_path = await generator.gen_speech(
                _build_bison_music_card_fallback_text(title),
                BISON_MUSIC_CARD_FALLBACK_VOICE_ID,
                music_enable=False,
            )
        except Exception as exc:
            logger.warning(f"Bison 生成音乐卡片提示语音失败：{cache_key} {exc}")
            return None, fallback_cache_key

        if not generated_path:
            logger.warning(f"Bison 生成音乐卡片提示语音失败：{cache_key} 未返回音频文件")
            return None, fallback_cache_key

        generated_file = Path(generated_path)
        if not generated_file.exists():
            logger.warning(f"Bison 生成音乐卡片提示语音失败：{cache_key} 文件不存在：{generated_file}")
            return None, fallback_cache_key

        try:
            expected_bytes = generated_file.stat().st_size
        except OSError:
            expected_bytes = None
        decision = ensure_optional_write_allowed(
            "Bison 提示语音缓存写入",
            target_mp3_path,
            expected_bytes=expected_bytes,
        )
        if not decision.allowed:
            logger.warning(decision.message)
            generated_file.unlink(missing_ok=True)
            return None, fallback_cache_key

        target_mp3_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            generated_file.replace(target_mp3_path)
        except Exception as exc:
            logger.warning(f"Bison 保存音乐卡片提示语音失败：{cache_key} {exc}")
            return None, fallback_cache_key
        cleanup_bison_music_card_cache(protected_paths=[target_mp3_path])
        return target_mp3_path, fallback_cache_key


async def _get_bison_music_card_upload_group_ids(target_group_id: int) -> list[int]:
    upload_group_ids: list[int] = []

    try:
        from src.services.registry import service_manager

        service = await service_manager.get_service(target_group_id, Services.Bison)
        raw_cache_group_id = getattr(service, "music_card_cache_group_id", None)
    except Exception as exc:
        logger.warning(f"Bison 读取音乐卡片缓存群配置失败：group={target_group_id} {exc}")
        raw_cache_group_id = None

    if raw_cache_group_id in (None, ""):
        cache_group_id = BISON_DEFAULT_MUSIC_CARD_CACHE_GROUP_ID
    else:
        try:
            cache_group_id = int(raw_cache_group_id)
        except (TypeError, ValueError):
            cache_group_id = BISON_DEFAULT_MUSIC_CARD_CACHE_GROUP_ID

    for group_id in (cache_group_id, int(target_group_id)):
        if group_id <= 0:
            continue
        if group_id in upload_group_ids:
            continue
        upload_group_ids.append(group_id)

    return upload_group_ids


async def _upload_bison_music_card_audio_url(target_group_id: int, audio_path: Path, cache_key: str) -> str | None:
    for upload_group_id in await _get_bison_music_card_upload_group_ids(int(target_group_id)):
        audio_url = await _get_or_upload_bison_audio_url(upload_group_id, audio_path, cache_key)
        if audio_url:
            return audio_url
    return None


async def _resolve_bison_music_card_audio_url(target_group_id: int, meta: dict[str, str]) -> str | None:
    audio_path, cache_key = await _ensure_bison_music_audio_file(meta["url"])
    if audio_path and cache_key:
        audio_url = await _upload_bison_music_card_audio_url(target_group_id, audio_path, cache_key)
        if audio_url:
            return audio_url

    fallback_base_key = cache_key or _get_bison_music_cache_key(meta["url"])
    if not fallback_base_key:
        return None

    fallback_audio_path, fallback_cache_key = await _ensure_bison_music_fallback_audio_file(
        fallback_base_key,
        meta["title"],
    )
    if not fallback_audio_path or not fallback_cache_key:
        return None

    return await _upload_bison_music_card_audio_url(target_group_id, fallback_audio_path, fallback_cache_key)


def _build_bison_music_card_messages(
    *,
    audio_url: str,
    video_url: str,
    title: str,
    cover_url: str,
    singer: str,
) -> list[Any]:
    saa_module = importlib.import_module("nonebot_plugin_saa")
    onebot_v11_module = importlib.import_module("nonebot.adapters.onebot.v11")

    custom_segment = saa_module.Custom(
        {
            saa_module.SupportedAdapters.onebot_v11: onebot_v11_module.MessageSegment(
                "music",
                {
                    "type": "custom",
                    "url": video_url,
                    "audio": audio_url,
                    "title": title,
                    "image": cover_url,
                    "singer": singer,
                },
            )
        }
    )
    return [saa_module.MessageFactory(custom_segment)]


async def _build_bison_messages_for_target(send_post: Any, send_target: Any) -> list[Any]:
    meta = _get_bison_music_card_meta(send_post)
    if not meta:
        if _is_bison_bilibili_video_post(send_post):
            logger.warning(f"Bison B站视频缺少音乐卡片元数据，跳过普通消息回退：{getattr(send_post, 'url', '')}")
            return []
        return await send_post.generate_messages()

    try:
        saa_module = importlib.import_module("nonebot_plugin_saa")
        if not isinstance(send_target, saa_module.TargetQQGroup):
            logger.warning(f"Bison 音乐卡片暂仅支持 QQ 群目标，跳过普通消息回退：{meta['url']}")
            return []

        audio_url = await _resolve_bison_music_card_audio_url(int(send_target.group_id), meta)
        if not audio_url:
            logger.warning(f"Bison 音乐卡片音频 URL 不可用，跳过普通消息回退：{meta['url']}")
            return []

        return _build_bison_music_card_messages(
            audio_url=audio_url,
            video_url=meta["url"],
            title=meta["title"],
            cover_url=meta["cover"],
            singer=meta["singer"],
        )
    except Exception as exc:
        logger.warning(f"Bison 音乐卡片构建失败，跳过普通消息回退：{exc}")
        return []


def _apply_bison_runtime_patches() -> None:
    global _RUNTIME_PATCHED
    if _RUNTIME_PATCHED:
        return

    platform_module = importlib.import_module("nonebot_bison.platform.platform")
    config_module = importlib.import_module("nonebot_bison.config")
    scheduler_module = importlib.import_module("nonebot_bison.scheduler.scheduler")
    db_config_module = importlib.import_module("nonebot_bison.config.db_config")
    plugin_config_module = importlib.import_module("nonebot_bison.plugin_config")
    bilibili_platform_module = importlib.import_module("nonebot_bison.platform.bilibili.platforms")
    send_module = importlib.import_module("nonebot_bison.send")
    skip_request_exception = importlib.import_module("nonebot_bison.utils.site").SkipRequestException
    no_bot_found_exception = importlib.import_module("nonebot_plugin_saa.utils.exceptions").NoBotFound
    new_message_cls = platform_module.NewMessage
    scheduler_cls = scheduler_module.Scheduler
    db_config_cls = db_config_module.DBConfig
    bilibili_cls = bilibili_platform_module.Bilibili
    original_filter = new_message_cls.filter_common_with_diff
    original_get_next_schedulable = scheduler_cls.get_next_schedulable
    original_run_schedulable_fetch = scheduler_cls._run_schedulable_fetch
    original_add_subscribe = db_config_cls.add_subscribe
    original_bilibili_parse = bilibili_cls.parse

    if not getattr(original_filter, "__bison_service_patched__", False):

        async def _service_filter_common_with_diff(self, target, raw_post_list):
            filtered_post = _filter_bison_posts_for_service(self, raw_post_list)
            state = _load_bison_target_state(
                platform_name=self.platform_name,
                target=target,
                cached_state=self.get_stored_data(target),
            )
            result_posts = []

            if not state["inited"]:
                if getattr(plugin_config_module.plugin_config, "bison_init_filter", True):
                    result_posts = _select_bison_bootstrap_posts(self, filtered_post, plugin_config_module.plugin_config)
                else:
                    result_posts = list(filtered_post)
                _track_bison_seen_posts(self, state, filtered_post)
                state["inited"] = True
                _save_bison_target_state(platform_name=self.platform_name, target=target, state=state)
                self.set_stored_data(target, dict(state))
                logger.info(f"init {self.platform_name}-{target} with {state['recent_post_ids']}")
            else:
                for raw_post in filtered_post:
                    if _is_bison_seen_post(self, state, raw_post):
                        continue
                    result_posts.append(raw_post)
                if filtered_post:
                    _track_bison_seen_posts(self, state, filtered_post)
                    _save_bison_target_state(platform_name=self.platform_name, target=target, state=state)
                    self.set_stored_data(target, dict(state))

            logger.trace(
                f"本次抓取 {len(raw_post_list)} 条，过滤后 {len(filtered_post)} 条，新消息 {len(result_posts)} 条"
            )
            return result_posts

        _service_filter_common_with_diff.__bison_service_patched__ = True
        _service_filter_common_with_diff.__wrapped__ = original_filter
        new_message_cls.filter_common_with_diff = _service_filter_common_with_diff

    if not getattr(original_get_next_schedulable, "__bison_service_patched__", False):

        async def _service_get_next_schedulable(self):
            if not self.schedulable_list:
                return None
            cur_weight = await config_module.config.get_current_weight_val(self.platform_name_list)
            weight_sum = self.pre_weight_val
            self.pre_weight_val = 0
            cur_max_schedulable = None
            for schedulable in self.schedulable_list:
                resolved_weight = _get_bison_schedulable_weight(cur_weight, schedulable)
                schedulable.current_weight += resolved_weight
                weight_sum += resolved_weight
                if not cur_max_schedulable or cur_max_schedulable.current_weight < schedulable.current_weight:
                    cur_max_schedulable = schedulable
            assert cur_max_schedulable
            cur_max_schedulable.current_weight -= weight_sum
            return cur_max_schedulable

        _service_get_next_schedulable.__bison_service_patched__ = True
        _service_get_next_schedulable.__wrapped__ = original_get_next_schedulable
        scheduler_cls.get_next_schedulable = _service_get_next_schedulable

    if not getattr(original_run_schedulable_fetch, "__bison_service_patched__", False):

        async def _service_run_schedulable_fetch(self, context, schedulable):
            success_flag = False
            platform_obj = scheduler_module.platform_manager[schedulable.platform_name](context)
            to_send = None
            try:
                with scheduler_module.request_time_histogram.labels(
                    platform_name=schedulable.platform_name, site_name=platform_obj.site.name
                ).time():
                    if schedulable.use_batch:
                        batch_targets = self.batch_api_target_cache[schedulable.platform_name][schedulable.target]
                        sub_units = []
                        for batch_target in batch_targets:
                            userinfo = await config_module.config.get_platform_target_subscribers(
                                schedulable.platform_name, batch_target
                            )
                            sub_units.append(scheduler_module.SubUnit(batch_target, userinfo))
                        to_send = await platform_obj.do_batch_fetch_new_post(sub_units)
                    else:
                        send_userinfo_list = await config_module.config.get_platform_target_subscribers(
                            schedulable.platform_name, schedulable.target
                        )
                        to_send = await platform_obj.do_fetch_new_post(
                            scheduler_module.SubUnit(schedulable.target, send_userinfo_list)
                        )
                    success_flag = True
            except skip_request_exception as err:
                logger.debug(f"skip request: {err}")
            except Exception as err:
                records = context.gen_req_records()
                for record in records:
                    logger.warning("API request record: " + record)
                err.args += (records,)
                raise

            scheduler_module.request_counter.labels(
                platform_name=schedulable.platform_name,
                site_name=platform_obj.site.name,
                target=schedulable.target,
                success=success_flag,
            ).inc()
            if not to_send:
                return
            scheduler_module.sent_counter.labels(
                platform_name=schedulable.platform_name,
                site_name=platform_obj.site.name,
                target=schedulable.target,
            ).inc()
            with scheduler_module.render_time_histogram.labels(
                platform_name=schedulable.platform_name, site_name=platform_obj.site.name
            ).time():
                for user, send_list in to_send:
                    for send_post in _select_bison_posts_for_delivery(schedulable.platform_name, send_list):
                        logger.info(f"send to {user}: {send_post}")
                        try:
                            messages = await _build_bison_messages_for_target(send_post, user)
                            if not messages:
                                continue
                            await send_module.send_msgs(
                                user,
                                messages,
                            )
                        except no_bot_found_exception:
                            logger.warning("no bot connected")

        _service_run_schedulable_fetch.__bison_service_patched__ = True
        _service_run_schedulable_fetch.__wrapped__ = original_run_schedulable_fetch
        scheduler_cls._run_schedulable_fetch = _service_run_schedulable_fetch

    if not getattr(original_add_subscribe, "__bison_service_patched__", False):

        async def _service_add_subscribe(self, user, target, target_name, platform_name, cats, tags):
            compat_module = importlib.import_module("nonebot.compat")
            datastore_module = importlib.import_module("nonebot_plugin_datastore")
            sqlalchemy_module = importlib.import_module("sqlalchemy")
            sqlalchemy_exc_module = importlib.import_module("sqlalchemy.exc")
            db_model_module = importlib.import_module("nonebot_bison.config.db_model")

            model_dump = compat_module.model_dump
            create_session = datastore_module.create_session
            select = sqlalchemy_module.select
            IntegrityError = sqlalchemy_exc_module.IntegrityError
            user_model = db_model_module.User
            target_model = db_model_module.Target
            subscribe_model = db_model_module.Subscribe

            is_new_target = False
            async with create_session() as session:
                db_user_stmt = select(user_model).where(user_model.user_target == model_dump(user))
                db_user = await session.scalar(db_user_stmt)
                if not db_user:
                    db_user = user_model(user_target=model_dump(user))
                    session.add(db_user)
                db_target_stmt = select(target_model).where(target_model.platform_name == platform_name).where(
                    target_model.target == target
                )
                db_target = await session.scalar(db_target_stmt)
                if not db_target:
                    db_target = target_model(target=target, platform_name=platform_name, target_name=target_name)
                    session.add(db_target)
                    is_new_target = True
                else:
                    db_target.target_name = target_name
                subscribe = subscribe_model(
                    categories=cats,
                    tags=tags,
                    user=db_user,
                    target=db_target,
                )
                session.add(subscribe)
                try:
                    await session.commit()
                except IntegrityError as exc:
                    if len(exc.args) > 0 and "UNIQUE constraint failed" in exc.args[0]:
                        raise db_config_module.SubscribeDupException()
                    raise

            if is_new_target:
                try:
                    await asyncio.gather(*[hook(platform_name, target) for hook in self.add_target_hook])
                except Exception as exc:
                    logger.warning(f"Bison 新目标注册到调度器失败，将等待后续调度恢复：{platform_name}-{target} {exc}")

        _service_add_subscribe.__bison_service_patched__ = True
        _service_add_subscribe.__wrapped__ = original_add_subscribe
        db_config_cls.add_subscribe = _service_add_subscribe

    if not getattr(original_bilibili_parse, "__bison_service_patched__", False):

        async def _service_bilibili_parse(self, raw_post):
            post = await original_bilibili_parse(self, raw_post)
            try:
                if int(self.get_category(raw_post)) != 3:
                    return post
            except Exception:
                return post
            _attach_bison_music_card_meta(post)
            return post

        _service_bilibili_parse.__bison_service_patched__ = True
        _service_bilibili_parse.__wrapped__ = original_bilibili_parse
        bilibili_cls.parse = _service_bilibili_parse

    _RUNTIME_PATCHED = True


def _iter_bison_plugin_config_modules(*, ensure_loaded: bool = False) -> list[ModuleType]:
    module_names = (
        "src.vendors.nonebot_bison.plugin_config",
        "nonebot_bison.plugin_config",
    )
    modules: list[ModuleType] = []
    for module_name in module_names:
        module = sys.modules.get(module_name)
        if module is None and ensure_loaded:
            try:
                module = importlib.import_module(module_name)
            except Exception:
                module = None
        if module is None:
            continue
        sys.modules["src.vendors.nonebot_bison.plugin_config"] = module
        sys.modules["nonebot_bison.plugin_config"] = module
        if module not in modules:
            modules.append(module)
    return modules


class BisonOwnerFacade:
    vendor_package = BISON_VENDOR_PACKAGE
    vendor_alias = BISON_VENDOR_ALIAS
    dependency_plugins = BISON_DEPENDENCY_PLUGINS
    support_modules = BISON_SUPPORT_MODULES
    entry_modules = BISON_ENTRY_MODULES
    vendor_context_modules = BISON_VENDOR_CONTEXT_MODULES

    def load_root_plugin(self):
        plugin = get_plugin("nonebot_bison")
        if plugin is not None:
            return plugin
        return load_plugin(self.vendor_package)

    def sync_vendor_aliases(self) -> None:
        prefix = f"{self.vendor_package}."
        alias_prefix = f"{self.vendor_alias}."
        for module_name, module in list(sys.modules.items()):
            if module_name == self.vendor_package:
                continue
            if not module_name.startswith(prefix):
                continue
            aliased_name = alias_prefix + module_name[len(prefix) :]
            sys.modules.setdefault(aliased_name, module)
        for module_name, module in list(sys.modules.items()):
            if module_name == self.vendor_alias:
                continue
            if not module_name.startswith(alias_prefix):
                continue
            vendor_name = prefix + module_name[len(alias_prefix) :]
            sys.modules.setdefault(vendor_name, module)

    def bind_vendor_alias(self) -> ModuleType:
        plugin = self.load_root_plugin()
        if plugin is None:
            vendor_package = importlib.import_module(self.vendor_package)
        else:
            vendor_package = plugin.module
        sys.modules[self.vendor_alias] = vendor_package
        sys.modules[self.vendor_package] = vendor_package
        self.sync_vendor_aliases()
        return vendor_package

    def require_dependencies(self) -> None:
        for plugin_name in self.dependency_plugins:
            require(plugin_name)

    def import_vendor_module(self, module_name: str) -> ModuleType:
        aliased_name = f"{self.vendor_alias}.{module_name}"
        vendor_name = f"{self.vendor_package}.{module_name}"

        if aliased_name in sys.modules:
            module = sys.modules[aliased_name]
        elif vendor_name in sys.modules:
            module = sys.modules[vendor_name]
        elif module_name in self.vendor_context_modules:
            module = importlib.import_module(vendor_name)
        else:
            module = importlib.import_module(aliased_name)

        self.sync_vendor_aliases()
        return module

    def load_support_modules(self) -> tuple[ModuleType, ...]:
        return tuple(self.import_vendor_module(module_name) for module_name in self.support_modules)

    def load_entry_modules(self) -> tuple[ModuleType, ...]:
        return tuple(self.import_vendor_module(module_name) for module_name in self.entry_modules)

    def activate_runtime(self) -> None:
        global _RUNTIME_ACTIVATED
        if _RUNTIME_ACTIVATED:
            return

        self.require_dependencies()

        import nonebot_plugin_saa

        self.load_root_plugin()
        self.bind_vendor_alias()
        _iter_bison_plugin_config_modules(ensure_loaded=True)
        self.load_support_modules()
        self.load_entry_modules()

        nonebot_plugin_saa.enable_auto_select_bot()
        _RUNTIME_ACTIVATED = True


BISON_OWNER = BisonOwnerFacade()


def activate_owned_vendor() -> None:
    BISON_OWNER.activate_runtime()
    _apply_bison_runtime_patches()


def ensure_bison_runtime_loaded() -> None:
    activate_owned_vendor()


class BisonService(BaseService):
    service_type = Services.Bison
    default_config = {"enabled": False}
    settings_schema = [
        {
            "key": "music_card_cache_group_id",
            "title": "音乐卡片缓存群",
            "description": "未设置时默认使用 750932711；填 0 表示关闭缓存群并继续上传到当前发送群。",
            "type": "int",
            "group": "音乐卡片",
            "min_value": 0,
        }
    ]
    enabled = config_property("enabled")
    music_card_cache_group_id = config_property("music_card_cache_group_id")

    async def _ensure_runtime(self) -> None:
        ensure_bison_runtime_loaded()

    async def _ensure_scheduler_ready(self, platform: str) -> None:
        from src.vendors.nonebot_bison.platform import platform_manager
        from src.vendors.nonebot_bison.scheduler import init_scheduler, scheduler_dict

        if platform not in platform_manager:
            raise ValueError(f"不支持的平台：{platform}")

        site = platform_manager[platform].site
        if site in scheduler_dict:
            return

        await init_scheduler()
        if site not in scheduler_dict:
            raise RuntimeError(f"订阅平台初始化失败：{platform}")

    async def _get_cookie_client_manager(self, platform: str):
        from src.vendors.nonebot_bison.platform import platform_manager
        from src.vendors.nonebot_bison.scheduler import scheduler_dict
        from src.vendors.nonebot_bison.utils.site import CookieClientManager, is_cookie_client_manager

        if platform not in platform_manager:
            raise ValueError(f"不支持的平台：{platform}")
        if not is_cookie_client_manager(platform_manager[platform].site.client_mgr):
            raise ValueError(f"平台 {platform} 暂不支持 Cookie")

        await self._ensure_scheduler_ready(platform)
        site = platform_manager[platform].site
        scheduler = scheduler_dict.get(site)
        if scheduler is None:
            raise RuntimeError(f"平台 {platform} 的调度器未初始化")
        return cast(CookieClientManager, scheduler.client_mgr)

    async def _prompt_bison_cookie_platform(self) -> str | None:
        from src.vendors.nonebot_bison.platform import platform_manager
        from src.vendors.nonebot_bison.utils.site import is_cookie_client_manager

        supported_platforms = [
            f"{platform_name}: {platform_manager[platform_name].name}"
            for platform_name in platform_manager
            if is_cookie_client_manager(platform_manager[platform_name].site.client_mgr)
        ]
        if not supported_platforms:
            await self.group.send_msg("当前没有支持 Cookie 的 Bison 平台")
            return None

        await self.group.send_msg(
            "请输入想要设置 Cookie 的平台：\n"
            + "\n".join(supported_platforms)
            + "\n发送“取消”可退出"
        )
        response = await wait_for(60)
        if not response or response == "取消":
            await self.group.send_msg("已取消设置 Bison Cookie")
            return None
        return response.strip()

    async def _prompt_bison_cookie_content(self) -> str | None:
        await self.group.send_msg("请发送完整 Cookie 内容\n发送“取消”可退出")
        response = await wait_for(180)
        if not response or response == "取消":
            await self.group.send_msg("已取消设置 Bison Cookie")
            return None
        cookie_text = response.strip()
        if not cookie_text:
            await self.group.send_msg("Cookie 内容不能为空")
            return None
        return cookie_text

    async def _probe_bison_cookie(self, platform: str, client_mgr, cookie_record) -> str:
        if platform != "bilibili":
            return "当前平台暂未提供在线可用性检测，Cookie 已保存。"

        return await self._probe_bilibili_cookie(client_mgr, cookie_record)

    async def _probe_bilibili_cookie(self, client_mgr, cookie_record) -> str:
        from src.vendors.nonebot_bison.utils.http import http_client
        from src.vendors.nonebot_bison.utils.site import parse_cookie

        cookie_dict = parse_cookie(cookie_record.content)
        uid = str(cookie_dict.get("DedeUserID", "")).strip()
        if not uid:
            return "Cookie 已保存，但未找到 DedeUserID，暂时无法执行 B 站动态接口检测。"

        params = {"host_mid": uid, "timezone_offset": -480, "offset": "", "features": "itemOpusStyle"}
        client = await client_mgr._assemble_client(http_client(), cookie_record)

        try:
            response = await client.get(
                "https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space",
                params=params,
                timeout=6.0,
            )
        except httpx.HTTPError as exc:
            return f"Cookie 已保存，但检测请求失败：{exc}"
        finally:
            await client.aclose()

        if response.status_code == 412:
            return (
                "Cookie 已保存，但 B 站动态接口返回 412。"
                "这说明当前服务端请求环境仍被 B 站风控拦截，不是 Cookie 没有写入。"
            )

        if response.status_code != 200:
            return f"Cookie 已保存，但检测接口返回 HTTP {response.status_code}，当前无法确认可用性。"

        try:
            payload = response.json()
        except ValueError:
            return "Cookie 已保存，但检测接口返回了非 JSON 内容，当前无法确认可用性。"

        code = payload.get("code")
        if code == 0:
            return "Cookie 已保存，且 B 站动态接口检测通过。"

        if code == -352:
            return "Cookie 已保存，但接口返回 -352，说明当前 Cookie 仍未通过 B 站动态接口校验。"

        message = payload.get("message") or payload.get("msg") or "未知错误"
        return f"Cookie 已保存，但检测接口返回 code={code}：{message}"

    @ai_tool(
        name="bison_subscribe",
        desc="订阅指定平台的 UP 主最新内容",
        parameters={
            "type": "object",
            "properties": {
                "platform": {"type": "string", "description": "平台名称，例如 bilibili"},
                "target": {"type": "string", "description": "目标用户 ID/UID"},
                "cats": {"type": "array", "items": {"type": "string"}, "description": "订阅分类，可选"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "订阅标签，可选"},
            },
            "required": ["platform", "target"],
        },
        category="bison",
        triggers=["订阅UP", "订阅"],
    )
    async def subscribe_up(
        self,
        user_id: int,
        group_id: int,
        platform: str,
        target: str,
        cats: list[str] | None = None,
        tags: list[str] | None = None,
        **kwargs,
    ) -> dict:
        if not self.enabled:
            return {"success": False, "message": "Bison 订阅服务未开启"}

        await self._ensure_runtime()
        try:
            from nonebot_plugin_saa import TargetQQGroup
            from src.vendors.nonebot_bison.apis import check_sub_target
            from src.vendors.nonebot_bison.config import config as bison_config
            from src.vendors.nonebot_bison.config.db_config import SubscribeDupException
            from src.vendors.nonebot_bison.types import Target as BisonTarget

            await self._ensure_scheduler_ready(platform)
            target_name = await check_sub_target(platform, target)
            if not target_name:
                return {"success": False, "message": "无法解析目标，请检查平台和 UID 是否正确"}

            user_target = TargetQQGroup(group_id=group_id)
            await bison_config.add_subscribe(
                user=user_target,
                target=BisonTarget(target),
                target_name=target_name,
                platform_name=platform,
                cats=cats or [],
                tags=tags or [],
            )
            return {"success": True, "message": f"已订阅 {target_name} ({platform} {target})"}
        except SubscribeDupException:
            return {"success": False, "message": "已存在该订阅"}
        except Exception as exc:
            return {"success": False, "message": f"订阅失败: {exc}"}

    @ai_tool(
        name="bison_unsubscribe",
        desc="取消订阅指定平台的 UP 主最新内容",
        parameters={
            "type": "object",
            "properties": {
                "platform": {"type": "string", "description": "平台名称，例如 bilibili"},
                "target": {"type": "string", "description": "目标用户 ID/UID"},
            },
            "required": ["platform", "target"],
        },
        category="bison",
        triggers=["取消订阅", "取关UP", "取关"],
    )
    async def unsubscribe_up(
        self,
        user_id: int,
        group_id: int,
        platform: str,
        target: str,
        **kwargs,
    ) -> dict:
        if not self.enabled:
            return {"success": False, "message": "Bison 订阅服务未开启"}

        await self._ensure_runtime()
        try:
            from nonebot_plugin_saa import TargetQQGroup
            from src.vendors.nonebot_bison.config import (
                NoSuchSubscribeException,
                NoSuchUserException,
                config as bison_config,
            )

            user_target = TargetQQGroup(group_id=group_id)
            sub_list = await bison_config.list_subscribe(user_target)
            matched_sub = next(
                (
                    sub
                    for sub in sub_list
                    if getattr(getattr(sub, "target", None), "platform_name", None) == platform
                    and str(getattr(getattr(sub, "target", None), "target", "")) == str(target)
                ),
                None,
            )
            if matched_sub is None:
                return {"success": False, "message": "未找到该订阅"}

            target_name = str(getattr(matched_sub.target, "target_name", "") or "").strip()
            await bison_config.del_subscribe(user_target, target, platform)
            if target_name:
                return {"success": True, "message": f"已取消订阅 {target_name} ({platform} {target})"}
            return {"success": True, "message": f"已取消订阅 ({platform} {target})"}
        except (NoSuchUserException, NoSuchSubscribeException):
            return {"success": False, "message": "未找到该订阅"}
        except Exception as exc:
            return {"success": False, "message": f"取消订阅失败: {exc}"}

    @service_action(
        cmd="添加BisonCookie",
        desc="为支持的平台录入 Bison Cookie",
        require_admin=True,
        allow_when_disabled=True,
    )
    async def set_bison_cookie(self):
        await self._ensure_runtime()

        platform = await self._prompt_bison_cookie_platform()
        if not platform:
            return

        try:
            client_mgr = await self._get_cookie_client_manager(platform)
        except Exception as exc:
            await self.group.send_msg(str(exc))
            return

        cookie_text = await self._prompt_bison_cookie_content()
        if not cookie_text:
            return

        if not await client_mgr.validate_cookie(cookie_text):
            await self.group.send_msg(
                "Cookie 校验失败，请检查格式或内容是否有效。\n"
                "详情可参考 https://nonebot-bison.netlify.app/usage/cookie.html"
            )
            return

        try:
            cookie_name = await client_mgr.get_cookie_name(cookie_text)
            new_cookie = await client_mgr.add_identified_cookie(cookie_text, cookie_name)
        except Exception as exc:
            await self.group.send_msg(f"设置 Bison Cookie 失败：{exc}")
            return

        probe_message = await self._probe_bison_cookie(platform, client_mgr, new_cookie)
        await self.group.send_msg(
            f"已添加 Bison Cookie：{new_cookie.cookie_name}\n"
            f"平台：{platform}\n"
            f"检测结果：{probe_message}"
        )

    @service_action(cmd="Bison订阅服务")
    async def bison_service_menu(self):
        if not self.enabled:
            await self.group.send_msg("❌ Bison订阅服务未开启！")
            return
        flow = {
            "title": "欢迎使用Bison订阅服务",
            "text": "订阅功能请通过 AI 工具调用；Cookie 可使用“设置BisonCookie”命令录入。",
        }
        await run_flow(self.group, flow)


__all__ = [
    "BISON_DEPENDENCY_PLUGINS",
    "BISON_ENTRY_MODULES",
    "BISON_OWNER",
    "BISON_SUPPORT_MODULES",
    "BISON_VENDOR_CONTEXT_MODULES",
    "BISON_VENDOR_ALIAS",
    "BISON_VENDOR_PACKAGE",
    "BisonOwnerFacade",
    "activate_owned_vendor",
    "ensure_bison_runtime_loaded",
    "BisonService",
]
