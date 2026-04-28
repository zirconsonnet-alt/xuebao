from typing import Any, Dict, Optional

from nonebot.adapters.onebot.v11 import GroupMessageEvent

from src.support.core import (
    AuditRepository,
    IdempotencyRepository,
    SessionRepository,
    SessionSnapshot,
    VoteRepository,
)


def start_vote_session(
    *,
    group_id: int,
    actor_id: Optional[int],
    session_repo: SessionRepository,
    idem_repo: IdempotencyRepository,
    audit_repo: AuditRepository,
    session_key: str,
    flow: str,
    ttl_seconds: int,
    idempotency_key: str,
    initial_data: Optional[Dict[str, Any]] = None,
    audit_context: Optional[Dict[str, Any]] = None,
) -> bool:
    session_repo.cleanup_expired_sessions()
    if not idem_repo.reserve(
        idem_key=idempotency_key,
        user_id=actor_id,
        action="vote_start",
        session_key=session_key,
    ):
        return False

    if not session_repo.create_session(
        session_key=session_key,
        flow=flow,
        owner_id=actor_id,
        ttl_seconds=ttl_seconds,
        initial_data=initial_data,
    ):
        return False

    audit_repo.record_event(
        group_id=group_id,
        actor_id=actor_id,
        action="vote_start",
        subject_type="vote",
        subject_id=session_key,
        session_key=session_key,
        result="success",
        context=audit_context or {},
    )
    return True


def finish_vote_session(
    *,
    group_id: int,
    actor_id: Optional[int],
    session_repo: SessionRepository,
    audit_repo: AuditRepository,
    session_key: str,
    audit_context: Optional[Dict[str, Any]] = None,
) -> None:
    session_repo.update_session_status(session_key, "finished")
    audit_repo.record_event(
        group_id=group_id,
        actor_id=actor_id,
        action="vote_finish",
        subject_type="vote",
        subject_id=session_key,
        session_key=session_key,
        result="success",
        context=audit_context or {},
    )


class VoteMetadataFacade:
    def __init__(
        self,
        *,
        group_id: int,
        session_repo: SessionRepository,
        idem_repo: IdempotencyRepository,
        audit_repo: AuditRepository,
        vote_repo: VoteRepository,
    ):
        self.group_id = group_id
        self.session_repo = session_repo
        self.idem_repo = idem_repo
        self.audit_repo = audit_repo
        self.vote_repo = vote_repo

    def cleanup_expired_sessions(self) -> int:
        return self.session_repo.cleanup_expired_sessions()

    def get_session(self, session_key: str) -> Optional[SessionSnapshot]:
        return self.session_repo.get_session(session_key)

    def create_session(
        self,
        *,
        session_key: str,
        flow: str,
        owner_id: Optional[int],
        ttl_seconds: int,
        initial_data: Optional[Dict[str, Any]] = None,
    ) -> bool:
        return self.session_repo.create_session(
            session_key=session_key,
            flow=flow,
            owner_id=owner_id,
            ttl_seconds=ttl_seconds,
            initial_data=initial_data,
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
        return self.session_repo.update_session_step(
            session_key=session_key,
            step=step,
            patch_data=patch_data,
            expected_version=expected_version,
            ttl_seconds=ttl_seconds,
        )

    def finish_session(self, session_key: str) -> bool:
        return self.session_repo.update_session_status(session_key, "finished")

    def cancel_session(self, session_key: str) -> bool:
        return self.session_repo.update_session_status(session_key, "cancelled")

    def reserve_idempotency_key(
        self,
        *,
        idem_key: str,
        user_id: Optional[int],
        action: str,
        session_key: Optional[str],
    ) -> bool:
        return self.idem_repo.reserve(
            idem_key=idem_key,
            user_id=user_id,
            action=action,
            session_key=session_key,
        )

    def record_audit_event(
        self,
        *,
        actor_id: Optional[int],
        action: str,
        subject_type: Optional[str],
        subject_id: Optional[str],
        session_key: Optional[str],
        result: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.audit_repo.record_event(
            group_id=self.group_id,
            actor_id=actor_id,
            action=action,
            subject_type=subject_type,
            subject_id=subject_id,
            session_key=session_key,
            result=result,
            context=context,
        )

    def start_vote_session(
        self,
        *,
        actor_id: Optional[int],
        session_key: str,
        flow: str,
        ttl_seconds: int,
        idempotency_key: str,
        initial_data: Optional[Dict[str, Any]] = None,
        audit_context: Optional[Dict[str, Any]] = None,
    ) -> bool:
        return start_vote_session(
            group_id=self.group_id,
            actor_id=actor_id,
            session_repo=self.session_repo,
            idem_repo=self.idem_repo,
            audit_repo=self.audit_repo,
            session_key=session_key,
            flow=flow,
            ttl_seconds=ttl_seconds,
            idempotency_key=idempotency_key,
            initial_data=initial_data,
            audit_context=audit_context,
        )

    def finish_vote_session(
        self,
        *,
        actor_id: Optional[int],
        session_key: str,
        audit_context: Optional[Dict[str, Any]] = None,
    ) -> None:
        finish_vote_session(
            group_id=self.group_id,
            actor_id=actor_id,
            session_repo=self.session_repo,
            audit_repo=self.audit_repo,
            session_key=session_key,
            audit_context=audit_context,
        )


def _build_session_key(group_id: int, flow: str, scope: str) -> str:
    return f"{group_id}:{flow}:{scope}"


def _build_idempotency_key(event: GroupMessageEvent, action: str, session_key: str) -> str:
    event_id = getattr(event, "event_id", None) or getattr(event, "message_id", None)
    self_id = getattr(event, "self_id", None)
    return f"{event.group_id}:{self_id}:{event_id}:{action}:{session_key}"


def _reserve_side_effect(
    metadata: VoteMetadataFacade,
    *,
    action: str,
    session_key: Optional[str],
    actor_id: Optional[int],
    subject_type: str,
    subject_id: Optional[str],
) -> bool:
    if not session_key:
        return False
    idem_key = f"{metadata.group_id}:{action}:{session_key}:{subject_type}:{subject_id}"
    return metadata.reserve_idempotency_key(
        idem_key=idem_key,
        user_id=actor_id,
        action=action,
        session_key=session_key,
    )


def _record_side_effect_audit(
    metadata: VoteMetadataFacade,
    *,
    actor_id: Optional[int],
    action: str,
    session_key: Optional[str],
    subject_type: str,
    subject_id: Optional[str],
    result: str,
    context: Dict,
) -> None:
    metadata.record_audit_event(
        actor_id=actor_id,
        action=action,
        subject_type=subject_type,
        subject_id=subject_id,
        session_key=session_key,
        result=result,
        context=context,
    )
