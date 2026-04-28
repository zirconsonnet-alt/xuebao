from datetime import datetime, timedelta
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.support.core import SessionSnapshot  # noqa: E402


class InMemorySessionRepository:
    def __init__(self):
        self._sessions: dict[str, SessionSnapshot] = {}

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

    def get_session(self, session_key: str):
        return self._sessions.get(session_key)

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
        self._sessions[session_key] = SessionSnapshot(
            session_key=session.session_key,
            flow=session.flow,
            step=step,
            data=merged,
            version=session.version + 1,
            status=session.status,
            expires_at=session.expires_at,
        )
        return True


def test_update_session_step_rejects_stale_expected_version() -> None:
    repo = InMemorySessionRepository()
    assert repo.create_session(
        session_key="k",
        flow="vote_create",
        owner_id=1,
        ttl_seconds=60,
        initial_data={"a": 1},
    )

    session0 = repo.get_session("k")
    assert session0 is not None
    assert session0.version == 0

    assert repo.update_session_step(
        session_key="k",
        step=1,
        patch_data={"b": 2},
        expected_version=0,
    )

    session1 = repo.get_session("k")
    assert session1 is not None
    assert session1.version == 1
    assert session1.data == {"a": 1, "b": 2}

    assert (
        repo.update_session_step(
            session_key="k",
            step=2,
            patch_data={"c": 3},
            expected_version=0,
        )
        is False
    )

    session_after = repo.get_session("k")
    assert session_after is not None
    assert session_after.step == 1
    assert session_after.data == {"a": 1, "b": 2}
