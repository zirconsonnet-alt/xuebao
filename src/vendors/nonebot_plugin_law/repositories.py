import json
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from src.support.core import (
    AuditRepository,
    IdempotencyRepository,
    SessionRepository,
    SessionSnapshot,
    VoteRepository,
)
from src.support.db import GroupDatabase


class SqliteAuditRepository(AuditRepository):
    def __init__(self, db: GroupDatabase):
        self.db = db

    def record_log(
        self,
        *,
        group_id: int,
        user_id: Optional[int],
        action: str,
        session_key: Optional[str],
        result: str,
    ) -> None:
        self.db.insert_audit_log(group_id, user_id, action, session_key, result)

    def record_event(
        self,
        *,
        group_id: int,
        actor_id: Optional[int],
        action: str,
        subject_type: Optional[str],
        subject_id: Optional[str],
        session_key: Optional[str],
        result: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        context_json = json.dumps(context or {}, ensure_ascii=False)
        self.db.insert_audit_event(
            group_id,
            actor_id,
            action,
            subject_type,
            subject_id,
            session_key,
            result,
            context_json,
        )


class SqliteIdempotencyRepository(IdempotencyRepository):
    def __init__(self, db: GroupDatabase, *, group_id: int):
        self.db = db
        self.group_id = group_id

    def reserve(
        self,
        *,
        idem_key: str,
        user_id: Optional[int],
        action: str,
        session_key: Optional[str],
    ) -> bool:
        return self.db.reserve_idempotency_key(
            idem_key,
            self.group_id,
            user_id,
            action,
            session_key,
        )


class SqliteSessionRepository(SessionRepository):
    def __init__(self, db: GroupDatabase):
        self.db = db

    def get_session(self, session_key: str) -> Optional[SessionSnapshot]:
        raw = self.db.get_session(session_key)
        if not raw:
            return None
        return SessionSnapshot(
            session_key=raw["session_key"],
            flow=raw["flow"],
            step=raw["step"],
            data=raw.get("data") or {},
            version=raw.get("version") or 0,
            status=raw.get("status") or "",
            expires_at=raw.get("expires_at"),
        )

    def create_session(
        self,
        *,
        session_key: str,
        flow: str,
        owner_id: Optional[int],
        ttl_seconds: int,
        initial_data: Optional[Dict[str, Any]] = None,
    ) -> bool:
        expires_at = datetime.now() + timedelta(seconds=ttl_seconds)
        return self.db.create_session(
            session_key=session_key,
            flow=flow,
            step=0,
            data=initial_data or {},
            owner_id=owner_id,
            expires_at=expires_at,
        )

    def update_session_step(
        self,
        *,
        session_key: str,
        step: int,
        patch_data: Optional[Dict[str, Any]],
        expected_version: int,
        ttl_seconds: Optional[int] = None,
    ) -> bool:
        session = self.db.get_session(session_key)
        if not session:
            return False
        merged = dict(session.get("data") or {})
        if patch_data:
            merged.update(patch_data)
        expires_at = datetime.now() + timedelta(seconds=ttl_seconds) if ttl_seconds else None
        return self.db.update_session_step(
            session_key=session_key,
            step=step,
            data=merged,
            expected_version=expected_version,
            expires_at=expires_at,
        )

    def update_session_status(self, session_key: str, status: str) -> bool:
        return self.db.update_session_status(session_key, status)

    def cleanup_expired_sessions(self) -> int:
        return self.db.cleanup_expired_sessions()


class SqliteVoteRepository(VoteRepository):
    def __init__(self, db: GroupDatabase):
        self.db = db

    def reserve_vote_record(
        self,
        *,
        session_key: str,
        user_id: int,
        option_idx: int,
    ) -> bool:
        return self.db.reserve_vote_record(session_key, user_id, option_idx)
