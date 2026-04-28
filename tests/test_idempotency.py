from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


class InMemoryIdempotencyRepository:
    def __init__(self):
        self._keys: set[str] = set()

    def reserve(self, *, idem_key: str, user_id, action: str, session_key) -> bool:
        if idem_key in self._keys:
            return False
        self._keys.add(idem_key)
        return True


def test_reserve_is_idempotent() -> None:
    repo = InMemoryIdempotencyRepository()
    assert repo.reserve(idem_key="k1", user_id=1, action="vote_start", session_key="s1") is True
    assert repo.reserve(idem_key="k1", user_id=1, action="vote_start", session_key="s1") is False

