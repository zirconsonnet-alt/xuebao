from typing import Dict, List, Optional

from src.support.core import VoteRepository


class VoteManager:
    def __init__(self):
        self.voted_users: List[int] = []
        self.options: Dict[int, Dict[str, str]] = {}
        self._session_key: Optional[str] = None
        self._vote_repo: Optional[VoteRepository] = None

    def configure_session(self, *, vote_repo: VoteRepository, session_key: str):
        self._vote_repo = vote_repo
        self._session_key = session_key

    def vote(self, user_id: int, idx: int) -> bool:
        if user_id in self.voted_users:
            return False
        if self._vote_repo and self._session_key:
            if not self._vote_repo.reserve_vote_record(
                session_key=self._session_key,
                user_id=user_id,
                option_idx=idx,
            ):
                return False
        self.options[idx]["votes"] += 1
        self.voted_users.append(user_id)
        return True

    def get_results(self) -> Dict:
        return self.options

    def set_option(self, idx: int, option: str):
        self.options[idx] = {"option": option.strip(), "votes": 0}

    def get_option(self, idx: int) -> str:
        return self.options.get(idx, None).get("option", None)
