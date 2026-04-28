"""内部 API 与 Codex 桥接支撑能力。"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import hmac
import json
import os
from pathlib import Path
import shutil
from typing import Any, Dict, List, Optional, Set, Tuple
import tempfile
import time
import uuid

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
import nonebot
from nonebot.adapters.onebot.v11 import MessageEvent
from pydantic import ValidationError

from .config import load_api_runtime_config, load_api_secrets_config
from ..core import ConfirmRequest, LoginRequest, ProvisionRequest
from ..db import (
    CodexInternalDatabase,
    InternalDatabase,
    confirm_bot_user,
    create_bot_session,
    provision_bot_user,
    reserve_bot_nonce,
)


@dataclass
class BotApiConfig:
    bot_secrets: Dict[str, str] = field(default_factory=dict)
    sign_tolerance_seconds: int = 60
    nonce_ttl_seconds: int = 300
    session_ttl_seconds: int = 604800
    cookie_secure: bool = True
    cookie_name: str = "session"

    @classmethod
    def load(cls, runtime_config: Dict[str, Any], secrets_config: Dict[str, Any]) -> "BotApiConfig":
        bot_runtime = runtime_config.get("bot_api")
        if not isinstance(bot_runtime, dict):
            bot_runtime = {}
        bot_secrets = secrets_config.get("bot_secrets")
        if not isinstance(bot_secrets, dict):
            bot_secrets = {}
        return cls(
            bot_secrets={str(key): str(value) for key, value in bot_secrets.items()},
            sign_tolerance_seconds=int(bot_runtime.get("sign_tolerance_seconds", 60)),
            nonce_ttl_seconds=int(bot_runtime.get("nonce_ttl_seconds", 300)),
            session_ttl_seconds=int(bot_runtime.get("session_ttl_seconds", 604800)),
            cookie_secure=bool(bot_runtime.get("cookie_secure", True)),
            cookie_name=str(bot_runtime.get("cookie_name", "session")),
        )


def _resolve_workdir(raw_workdir: str) -> Path:
    workdir = Path(raw_workdir).expanduser()
    if not workdir.is_absolute():
        workdir = (Path.cwd() / workdir).resolve()
    else:
        workdir = workdir.resolve()
    if not workdir.exists():
        raise FileNotFoundError(f"Codex 工作目录不存在：{workdir}")
    if not workdir.is_dir():
        raise NotADirectoryError(f"Codex 工作目录不是目录：{workdir}")
    return workdir


def _resolve_executable(raw_executable: str) -> str:
    executable = Path(raw_executable).expanduser()
    looks_like_path = executable.is_absolute() or any(sep in raw_executable for sep in ("\\", "/"))
    if looks_like_path:
        candidates = [executable]
        if os.name == "nt" and not executable.suffix:
            candidates.extend(executable.with_suffix(suffix) for suffix in (".exe", ".cmd", ".bat"))
        for candidate in candidates:
            if candidate.is_file():
                return str(candidate.resolve())
        raise FileNotFoundError(f"未找到 Codex 可执行文件：{raw_executable}")

    names = [raw_executable]
    if os.name == "nt" and "." not in Path(raw_executable).name:
        names = [f"{raw_executable}.exe", raw_executable, f"{raw_executable}.cmd", f"{raw_executable}.bat"]
    seen = set()
    for name in names:
        if name in seen:
            continue
        seen.add(name)
        resolved = shutil.which(name)
        if resolved:
            return str(Path(resolved).resolve())
    raise FileNotFoundError(f"未找到 Codex 可执行文件：{raw_executable}")


@dataclass
class CodexBridgeConfig:
    command: List[str] = field(default_factory=list)
    workdir: str = r"I:\Projects"
    timeout_seconds: int = 1800
    max_concurrent_jobs: int = 1
    result_max_chars: int = 4000
    history_limit: int = 5
    allowed_user_ids: Set[int] = field(default_factory=set)
    allowed_group_ids: Set[int] = field(default_factory=set)
    at_sender_in_group: bool = True

    @classmethod
    def load(cls, runtime_config: Dict[str, Any]) -> "CodexBridgeConfig":
        bridge_runtime = runtime_config.get("codex_bridge")
        if not isinstance(bridge_runtime, dict):
            bridge_runtime = {}
        return cls(
            command=[str(item) for item in bridge_runtime.get("command", []) if str(item).strip()],
            workdir=str(bridge_runtime.get("workdir", r"I:\Projects")),
            timeout_seconds=int(bridge_runtime.get("timeout_seconds", 1800)),
            max_concurrent_jobs=int(bridge_runtime.get("max_concurrent_jobs", 1)),
            result_max_chars=int(bridge_runtime.get("result_max_chars", 4000)),
            history_limit=int(bridge_runtime.get("history_limit", 5)),
            allowed_user_ids={int(item) for item in bridge_runtime.get("allowed_user_ids", [])},
            allowed_group_ids={int(item) for item in bridge_runtime.get("allowed_group_ids", [])},
            at_sender_in_group=bool(bridge_runtime.get("at_sender_in_group", True)),
        )

    def resolve_command(self) -> List[str]:
        if not self.command:
            raise ValueError("CODEX_BRIDGE_COMMAND 不能为空。")
        return [_resolve_executable(self.command[0]), *self.command[1:]]

    def resolve_workdir(self) -> Path:
        return _resolve_workdir(self.workdir)


_api_runtime_config = load_api_runtime_config()
_api_secrets_config = load_api_secrets_config()
bot_api_config = BotApiConfig.load(_api_runtime_config, _api_secrets_config)
codex_bridge_config = CodexBridgeConfig.load(_api_runtime_config)


@dataclass
class CodexJobContext:
    job_id: str
    bot_self_id: str
    user_id: int
    group_id: Optional[int]
    chat_type: str
    prompt: str
    source_message_id: Optional[str]
    command: List[str]
    workdir: str
    codex_session_id: Optional[str]
    resume_mode: str


class CodexBridge:
    def __init__(self):
        self._db = CodexInternalDatabase()
        self._semaphore = asyncio.Semaphore(max(1, codex_bridge_config.max_concurrent_jobs))
        self._tasks: Dict[str, asyncio.Task] = {}
        self._processes: Dict[str, asyncio.subprocess.Process] = {}

    def is_allowed(self, event: MessageEvent) -> bool:
        if codex_bridge_config.allowed_user_ids and int(event.user_id) not in codex_bridge_config.allowed_user_ids:
            return False
        group_id = getattr(event, "group_id", None)
        if group_id and codex_bridge_config.allowed_group_ids and int(group_id) not in codex_bridge_config.allowed_group_ids:
            return False
        return True

    def get_runtime_info(self) -> Dict[str, Any]:
        info: Dict[str, Any] = {
            "configured_command": list(codex_bridge_config.command),
            "configured_workdir": codex_bridge_config.workdir,
        }
        try:
            resolved_command = codex_bridge_config.resolve_command()
            info["resolved_command"] = resolved_command
            info["resolved_executable"] = resolved_command[0]
        except Exception as exc:
            info["command_error"] = str(exc)
        try:
            resolved_workdir = codex_bridge_config.resolve_workdir()
            info["resolved_workdir"] = str(resolved_workdir)
        except Exception as exc:
            info["workdir_error"] = str(exc)
        info["ready"] = "command_error" not in info and "workdir_error" not in info
        return info

    def _ensure_runtime_ready(self) -> Tuple[List[str], str]:
        try:
            command = codex_bridge_config.resolve_command()
            workdir = str(codex_bridge_config.resolve_workdir())
        except Exception as exc:
            raise RuntimeError(f"Codex 桥接未就绪：{exc}") from exc
        return command, workdir

    def create_job(self, event: MessageEvent, prompt: str) -> CodexJobContext:
        command, workdir = self._ensure_runtime_ready()
        job_id = uuid.uuid4().hex[:8]
        group_id = getattr(event, "group_id", None)
        chat_type = "group" if group_id else "private"
        codex_session_id = self._db.get_latest_codex_session(user_id=int(event.user_id))
        resume_mode = "resume" if codex_session_id else "new"
        ctx = CodexJobContext(
            job_id=job_id,
            bot_self_id=str(getattr(event, "self_id", "") or ""),
            user_id=int(event.user_id),
            group_id=int(group_id) if group_id else None,
            chat_type=chat_type,
            prompt=prompt,
            source_message_id=str(getattr(event, "message_id", "") or ""),
            command=command,
            workdir=workdir,
            codex_session_id=codex_session_id,
            resume_mode=resume_mode,
        )
        self._db.create_codex_job(
            job_id=ctx.job_id,
            bot_self_id=ctx.bot_self_id or None,
            user_id=ctx.user_id,
            group_id=ctx.group_id,
            chat_type=ctx.chat_type,
            prompt=ctx.prompt,
            status="queued",
            command_text=" ".join(ctx.command),
            codex_session_id=ctx.codex_session_id,
            resume_mode=ctx.resume_mode,
            source_message_id=ctx.source_message_id or None,
        )
        self._tasks[ctx.job_id] = asyncio.create_task(self._run_job(ctx))
        return ctx

    def get_job(self, job_id: str):
        return self._db.get_codex_job(job_id)

    def list_jobs(self, user_id: int):
        return self._db.list_codex_jobs(user_id=user_id, limit=codex_bridge_config.history_limit)

    @staticmethod
    def _uses_stdin(ctx: CodexJobContext) -> bool:
        return ctx.resume_mode != "resume"

    def _build_exec_command(self, ctx: CodexJobContext, output_path: Path) -> List[str]:
        command = [
            *ctx.command,
            "-C",
            ctx.workdir,
            "--json",
            "-o",
            str(output_path),
        ]
        if ctx.resume_mode == "resume" and ctx.codex_session_id:
            return [*command, "resume", ctx.codex_session_id, ctx.prompt]
        return [*command, "-"]

    @staticmethod
    def _should_fallback_to_new(
        ctx: CodexJobContext,
        returncode: int,
        stdout: bytes,
        stderr: bytes,
    ) -> bool:
        if ctx.resume_mode != "resume" or returncode == 0:
            return False
        text = "\n".join(
            part.decode("utf-8", errors="ignore").lower()
            for part in (stdout, stderr)
            if part
        )
        if not text:
            return False
        session_markers = ("session", "thread", "conversation", "resume")
        failure_markers = (
            "not found",
            "no such",
            "missing",
            "unknown",
            "invalid",
            "expired",
            "archive",
            "archived",
            "cannot resume",
            "failed to resume",
        )
        return any(marker in text for marker in session_markers) and any(
            marker in text for marker in failure_markers
        )

    @staticmethod
    def _extract_codex_session_id(stdout: bytes) -> Optional[str]:
        for raw_line in stdout.decode("utf-8", errors="ignore").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if data.get("type") == "thread.started":
                thread_id = data.get("thread_id")
                if isinstance(thread_id, str) and thread_id:
                    return thread_id
        return None

    async def cancel_job(self, *, job_id: str, user_id: int) -> bool:
        job = self._db.get_codex_job(job_id)
        if not job or int(job["user_id"]) != int(user_id):
            return False
        status = job.get("status")
        if status in {"succeeded", "failed", "cancelled", "timeout"}:
            return False
        process = self._processes.get(job_id)
        if process and process.returncode is None:
            process.kill()
            try:
                await process.wait()
            except Exception:
                pass
        task = self._tasks.get(job_id)
        if task and not task.done():
            task.cancel()
        self._db.update_codex_job_status(
            job_id=job_id,
            status="cancelled",
            finished_at=datetime.now(),
            error_text="任务已取消。",
        )
        return True

    async def run_selftest(self) -> Dict[str, Any]:
        info = self.get_runtime_info()
        if not info.get("ready"):
            return info

        try:
            process = await asyncio.create_subprocess_exec(
                str(info["resolved_executable"]),
                "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(info["resolved_workdir"]),
            )
            stdout, stderr = await process.communicate()
            version_text = stdout.decode("utf-8", errors="ignore").strip()
            error_text = stderr.decode("utf-8", errors="ignore").strip()
            if process.returncode == 0:
                info["version"] = version_text or "(空输出)"
            else:
                info["version_error"] = error_text or version_text or f"版本检查失败，退出码 {process.returncode}"
        except Exception as exc:
            info["version_error"] = str(exc)
        return info

    async def _run_job(self, ctx: CodexJobContext) -> None:
        output_path = Path(tempfile.gettempdir()) / f"codex_bridge_{ctx.job_id}.txt"
        try:
            async with self._semaphore:
                self._db.update_codex_job_status(
                    job_id=ctx.job_id,
                    status="running",
                    codex_session_id=ctx.codex_session_id,
                    resume_mode=ctx.resume_mode,
                    started_at=datetime.now(),
                )
                while True:
                    command = self._build_exec_command(ctx, output_path)
                    use_stdin = self._uses_stdin(ctx)
                    process = await asyncio.create_subprocess_exec(
                        *command,
                        stdin=asyncio.subprocess.PIPE if use_stdin else None,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                        cwd=ctx.workdir,
                    )
                    self._processes[ctx.job_id] = process
                    try:
                        stdout, stderr = await asyncio.wait_for(
                            process.communicate(ctx.prompt.encode("utf-8") if use_stdin else None),
                            timeout=codex_bridge_config.timeout_seconds,
                        )
                    except asyncio.TimeoutError:
                        process.kill()
                        await process.wait()
                        self._db.update_codex_job_status(
                            job_id=ctx.job_id,
                            status="timeout",
                            finished_at=datetime.now(),
                            error_text="Codex 执行超时。",
                        )
                        await self._notify_completion(ctx, "timeout", "", "Codex 执行超时。")
                        return
                    if not self._should_fallback_to_new(ctx, process.returncode, stdout, stderr):
                        break
                    ctx.codex_session_id = None
                    ctx.resume_mode = "fallback-new"
                    self._db.update_codex_job_status(
                        job_id=ctx.job_id,
                        status="running",
                        codex_session_id=None,
                        resume_mode=ctx.resume_mode,
                    )

                result_text = ""
                codex_session_id = ctx.codex_session_id or self._extract_codex_session_id(stdout)
                if output_path.exists():
                    result_text = output_path.read_text(encoding="utf-8", errors="ignore").strip()
                if not result_text and stdout:
                    result_text = stdout.decode("utf-8", errors="ignore").strip()
                error_text = stderr.decode("utf-8", errors="ignore").strip()

                if process.returncode == 0:
                    if not result_text:
                        result_text = "Codex 已完成，但没有返回正文。"
                    self._db.update_codex_job_status(
                        job_id=ctx.job_id,
                        status="succeeded",
                        result_text=result_text,
                        codex_session_id=codex_session_id,
                        resume_mode=ctx.resume_mode,
                        finished_at=datetime.now(),
                    )
                    await self._notify_completion(ctx, "succeeded", result_text, "")
                else:
                    if not error_text:
                        error_text = result_text or f"Codex 执行失败，退出码 {process.returncode}"
                    self._db.update_codex_job_status(
                        job_id=ctx.job_id,
                        status="failed",
                        result_text=result_text or None,
                        error_text=error_text,
                        codex_session_id=codex_session_id,
                        resume_mode=ctx.resume_mode,
                        finished_at=datetime.now(),
                    )
                    await self._notify_completion(ctx, "failed", result_text, error_text)
        except asyncio.CancelledError:
            return
        except Exception as exc:
            self._db.update_codex_job_status(
                job_id=ctx.job_id,
                status="failed",
                error_text=str(exc),
                finished_at=datetime.now(),
            )
            await self._notify_completion(ctx, "failed", "", str(exc))
        finally:
            self._tasks.pop(ctx.job_id, None)
            self._processes.pop(ctx.job_id, None)
            try:
                output_path.unlink(missing_ok=True)
            except Exception:
                pass

    async def _notify_completion(
        self,
        ctx: CodexJobContext,
        status: str,
        result_text: str,
        error_text: str,
    ) -> None:
        bots = nonebot.get_bots()
        bot = bots.get(ctx.bot_self_id) if ctx.bot_self_id else None
        if bot is None and bots:
            bot = next(iter(bots.values()))
        if bot is None:
            return
        title = f"[Codex {ctx.job_id}] "
        if status == "succeeded":
            prefix = title + "执行完成。"
            body = result_text
        elif status == "timeout":
            prefix = title + "执行超时。"
            body = error_text or "Codex 执行超时。"
        elif status == "cancelled":
            prefix = title + "任务已取消。"
            body = error_text or "任务已取消。"
        else:
            prefix = title + "执行失败。"
            body = error_text or result_text or "未知错误。"

        chunks = self._split_message(body)
        if ctx.chat_type == "group" and ctx.group_id:
            at_prefix = f"[CQ:at,qq={ctx.user_id}] " if codex_bridge_config.at_sender_in_group else ""
            await bot.send_group_msg(group_id=ctx.group_id, message=at_prefix + prefix)
            for chunk in chunks:
                await bot.send_group_msg(group_id=ctx.group_id, message=chunk)
        else:
            await bot.send_private_msg(user_id=ctx.user_id, message=prefix)
            for chunk in chunks:
                await bot.send_private_msg(user_id=ctx.user_id, message=chunk)

    def _split_message(self, text: str) -> List[str]:
        if not text:
            return ["(空结果)"]
        limit = max(500, codex_bridge_config.result_max_chars)
        lines = text.splitlines()
        chunks: List[str] = []
        current = ""
        for line in lines:
            candidate = line if not current else f"{current}\n{line}"
            if len(candidate) <= limit:
                current = candidate
                continue
            if current:
                chunks.append(current)
            if len(line) <= limit:
                current = line
            else:
                start = 0
                while start < len(line):
                    chunks.append(line[start : start + limit])
                    start += limit
                current = ""
        if current:
            chunks.append(current)
        return chunks or [text[:limit]]


codex_bridge = CodexBridge()

internal_api_router = APIRouter()
_internal_db: Optional[InternalDatabase] = None


def _get_internal_db() -> InternalDatabase:
    global _internal_db
    if _internal_db is None:
        _internal_db = InternalDatabase()
    return _internal_db


def _parse_json_body(body_text: str) -> Dict[str, Any]:
    if not body_text:
        return {}
    return json.loads(body_text)


def _validate_dto(model_cls, payload: Dict[str, Any]):
    if hasattr(model_cls, "model_validate"):
        return model_cls.model_validate(payload)
    return model_cls.parse_obj(payload)


def _get_session_cookie(request: Request) -> str:
    return (request.cookies.get(bot_api_config.cookie_name) or "").strip()


def _get_authenticated_user(request: Request) -> Dict[str, Any]:
    session_id = _get_session_cookie(request)
    if not session_id:
        raise HTTPException(status_code=401, detail="missing session cookie")

    db = _get_internal_db()
    db.cleanup_expired_bot_sessions()
    session = db.get_bot_session(session_id)
    if not session:
        raise HTTPException(status_code=401, detail="invalid or expired session")

    user = db.get_bot_user_by_id(session["user_id"])
    if not user or user.get("status") != "active":
        db.delete_bot_session(session_id)
        raise HTTPException(status_code=401, detail="invalid or inactive user")

    return {
        "session_id": session_id,
        "user": user,
        "session": session,
    }


async def _verify_bot_request(request: Request) -> str:
    if not bot_api_config.bot_secrets:
        raise HTTPException(status_code=503, detail="bot secrets not configured")
    bot_id = request.headers.get("X-Bot-Id", "").strip()
    timestamp = request.headers.get("X-Timestamp", "").strip()
    nonce = request.headers.get("X-Nonce", "").strip()
    signature = request.headers.get("X-Signature", "").strip()

    if not bot_id or not timestamp or not nonce or not signature:
        raise HTTPException(status_code=401, detail="missing auth headers")
    secret = bot_api_config.bot_secrets.get(bot_id)
    if not secret:
        raise HTTPException(status_code=401, detail="unknown bot id")

    try:
        timestamp_int = int(timestamp)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="invalid timestamp") from exc
    if abs(int(__import__("time").time()) - timestamp_int) > bot_api_config.sign_tolerance_seconds:
        raise HTTPException(status_code=401, detail="timestamp out of range")

    body_bytes = await request.body()
    body_text = body_bytes.decode("utf-8") if body_bytes else ""
    path = request.url.path
    method = request.method.upper()
    sign_base = f"{method}\n{path}\n{body_text}\n{timestamp}\n{nonce}"
    expected = hmac.new(
        secret.encode("utf-8"),
        sign_base.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail="invalid signature")

    db = _get_internal_db()
    if not reserve_bot_nonce(db, bot_id, nonce, bot_api_config.nonce_ttl_seconds):
        raise HTTPException(status_code=401, detail="nonce already used")
    return body_text


@internal_api_router.post("/internal/provision")
async def internal_provision(request: Request):
    body_text = await _verify_bot_request(request)
    try:
        payload = _parse_json_body(body_text)
        dto = _validate_dto(ProvisionRequest, payload)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise HTTPException(status_code=400, detail=f"invalid payload: {exc}") from exc

    db = _get_internal_db()
    user = provision_bot_user(db, dto.qq_uin, dto.display_name)
    return {
        "status": user["status"],
        "secret": user["secret"],
        "user_id": user["user_id"],
    }


@internal_api_router.post("/internal/confirm")
async def internal_confirm(request: Request):
    body_text = await _verify_bot_request(request)
    try:
        payload = _parse_json_body(body_text)
        dto = _validate_dto(ConfirmRequest, payload)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise HTTPException(status_code=400, detail=f"invalid payload: {exc}") from exc

    db = _get_internal_db()
    user = confirm_bot_user(db, dto.qq_uin)
    if not user:
        raise HTTPException(status_code=404, detail="user not found")
    return {"status": "active", "user_id": user["user_id"]}


@internal_api_router.get("/internal/user_status")
async def internal_user_status(request: Request):
    await _verify_bot_request(request)
    qq_uin = (request.query_params.get("qq_uin") or "").strip()
    if not qq_uin:
        raise HTTPException(status_code=400, detail="missing qq_uin")

    db = _get_internal_db()
    user = db.get_bot_user_by_qq(qq_uin)
    if not user:
        return {"status": None, "display_name": None, "last_login_at": None}
    return {
        "status": user.get("status"),
        "display_name": user.get("display_name"),
        "last_login_at": user.get("last_login_at"),
    }


@internal_api_router.get("/internal/rank")
async def internal_rank(request: Request):
    await _verify_bot_request(request)
    qq_uin = (request.query_params.get("qq_uin") or "").strip()
    if not qq_uin:
        raise HTTPException(status_code=400, detail="missing qq_uin")

    db = _get_internal_db()
    user = db.get_bot_user_by_qq(qq_uin)
    if not user:
        return {"rank": None, "mmr": None, "wins": None, "losses": None}
    rank = db.get_bot_rank(user["user_id"]) or {}
    return {
        "rank": rank.get("rank"),
        "mmr": rank.get("mmr"),
        "wins": rank.get("wins"),
        "losses": rank.get("losses"),
    }


@internal_api_router.post("/auth/login")
async def auth_login(request: Request):
    try:
        payload = await request.json()
        dto = _validate_dto(LoginRequest, payload)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise HTTPException(status_code=400, detail=f"invalid payload: {exc}") from exc

    db = _get_internal_db()
    session = create_bot_session(
        db,
        qq_uin=dto.qq_uin,
        secret=dto.secret,
        ttl_seconds=bot_api_config.session_ttl_seconds,
    )
    if not session:
        raise HTTPException(status_code=401, detail="invalid credentials or inactive user")

    response = JSONResponse({"status": "ok", "user_id": session["user_id"]})
    response.set_cookie(
        bot_api_config.cookie_name,
        session["session_id"],
        httponly=True,
        samesite="lax",
        max_age=bot_api_config.session_ttl_seconds,
        secure=bot_api_config.cookie_secure,
    )
    return response


@internal_api_router.get("/auth/me")
async def auth_me(request: Request):
    auth = _get_authenticated_user(request)
    user = auth["user"]
    return {
        "status": "ok",
        "user_id": user["user_id"],
        "qq_uin": user["qq_uin"],
        "display_name": user.get("display_name"),
        "last_login_at": user.get("last_login_at"),
    }


@internal_api_router.post("/auth/logout")
async def auth_logout(request: Request):
    session_id = _get_session_cookie(request)
    if session_id:
        _get_internal_db().delete_bot_session(session_id)

    response = JSONResponse({"status": "ok"})
    response.delete_cookie(bot_api_config.cookie_name)
    return response


