from datetime import datetime, timedelta
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.services.vote import VoteMetadataFacade  # noqa: E402
from src.support.core import SessionSnapshot  # noqa: E402


class InMemorySessionRepository:
    def __init__(self):
        self._sessions: dict[str, SessionSnapshot] = {}

    def get_session(self, session_key: str):
        return self._sessions.get(session_key)

    def create_session(
        self,
        *,
        session_key: str,
        flow: str,
        owner_id,
        ttl_seconds: int,
        initial_data=None,
    ) -> bool:
        if session_key in self._sessions:
            return False
        expires_at = (datetime.now() + timedelta(seconds=ttl_seconds)).isoformat()
        self._sessions[session_key] = SessionSnapshot(
            session_key=session_key,
            flow=flow,
            step=0,
            data=initial_data or {},
            version=0,
            status="active",
            expires_at=expires_at,
        )
        return True

    def update_session_step(
        self,
        *,
        session_key: str,
        step: int,
        patch_data,
        expected_version: int,
        ttl_seconds=None,
    ) -> bool:
        session = self._sessions.get(session_key)
        if not session:
            return False
        if session.version != expected_version:
            return False
        merged = dict(session.data or {})
        if patch_data:
            merged.update(patch_data)
        expires_at = session.expires_at
        if ttl_seconds is not None:
            expires_at = (datetime.now() + timedelta(seconds=ttl_seconds)).isoformat()
        self._sessions[session_key] = SessionSnapshot(
            session_key=session.session_key,
            flow=session.flow,
            step=step,
            data=merged,
            version=session.version + 1,
            status=session.status,
            expires_at=expires_at,
        )
        return True

    def update_session_status(self, session_key: str, status: str) -> bool:
        session = self._sessions.get(session_key)
        if not session:
            return False
        self._sessions[session_key] = SessionSnapshot(
            session_key=session.session_key,
            flow=session.flow,
            step=session.step,
            data=session.data,
            version=session.version,
            status=status,
            expires_at=session.expires_at,
        )
        return True

    def cleanup_expired_sessions(self) -> int:
        return 0


class InMemoryIdempotencyRepository:
    def __init__(self):
        self._keys: set[str] = set()

    def reserve(self, *, idem_key: str, user_id, action: str, session_key) -> bool:
        if idem_key in self._keys:
            return False
        self._keys.add(idem_key)
        return True


class InMemoryAuditRepository:
    def __init__(self):
        self.events: list[dict] = []

    def record_log(self, *, group_id: int, user_id, action: str, session_key, result: str) -> None:
        self.events.append(
            {
                "group_id": group_id,
                "actor_id": user_id,
                "action": action,
                "subject_type": None,
                "subject_id": None,
                "session_key": session_key,
                "result": result,
                "context": None,
            }
        )

    def record_event(
        self,
        *,
        group_id: int,
        actor_id,
        action: str,
        subject_type,
        subject_id,
        session_key,
        result: str,
        context=None,
    ) -> None:
        self.events.append(
            {
                "group_id": group_id,
                "actor_id": actor_id,
                "action": action,
                "subject_type": subject_type,
                "subject_id": subject_id,
                "session_key": session_key,
                "result": result,
                "context": context,
            }
        )


class InMemoryVoteRepository:
    def reserve_vote_record(self, *, session_key: str, user_id: int, option_idx: int) -> bool:
        return True


def test_vote_metadata_facade_start_is_idempotent_and_records_audit() -> None:
    session_repo = InMemorySessionRepository()
    idem_repo = InMemoryIdempotencyRepository()
    audit_repo = InMemoryAuditRepository()
    vote_repo = InMemoryVoteRepository()

    facade = VoteMetadataFacade(
        group_id=123,
        session_repo=session_repo,
        idem_repo=idem_repo,
        audit_repo=audit_repo,
        vote_repo=vote_repo,
    )

    ok = facade.start_vote_session(
        actor_id=456,
        session_key="123:vote_active:group",
        flow="vote_create",
        ttl_seconds=60,
        idempotency_key="idem-1",
        initial_data={"strategy": "TopicStrategy"},
        audit_context={"strategy": "TopicStrategy"},
    )
    assert ok is True
    assert [e["action"] for e in audit_repo.events] == ["vote_start"]

    ok2 = facade.start_vote_session(
        actor_id=456,
        session_key="123:vote_active:group",
        flow="vote_create",
        ttl_seconds=60,
        idempotency_key="idem-1",
        initial_data={"strategy": "TopicStrategy"},
        audit_context={"strategy": "TopicStrategy"},
    )
    assert ok2 is False
    assert [e["action"] for e in audit_repo.events] == ["vote_start"]


def test_vote_metadata_facade_finish_updates_status_and_records_audit() -> None:
    session_repo = InMemorySessionRepository()
    idem_repo = InMemoryIdempotencyRepository()
    audit_repo = InMemoryAuditRepository()
    vote_repo = InMemoryVoteRepository()

    facade = VoteMetadataFacade(
        group_id=123,
        session_repo=session_repo,
        idem_repo=idem_repo,
        audit_repo=audit_repo,
        vote_repo=vote_repo,
    )

    assert (
        facade.start_vote_session(
            actor_id=456,
            session_key="123:vote_active:group",
            flow="vote_create",
            ttl_seconds=60,
            idempotency_key="idem-2",
            initial_data={"strategy": "TopicStrategy"},
            audit_context={"strategy": "TopicStrategy"},
        )
        is True
    )

    facade.finish_vote_session(
        actor_id=456,
        session_key="123:vote_active:group",
        audit_context={"voters": 1},
    )

    session = session_repo.get_session("123:vote_active:group")
    assert session is not None
    assert session.status == "finished"
    assert [e["action"] for e in audit_repo.events] == ["vote_start", "vote_finish"]
