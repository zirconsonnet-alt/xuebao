from typing import TYPE_CHECKING

from .governance import GovernanceManager
from .metadata import VoteMetadataFacade
from .repositories import (
    SqliteAuditRepository,
    SqliteIdempotencyRepository,
    SqliteSessionRepository,
    SqliteVoteRepository,
)
from .spec import GOVERNANCE_DEFAULT_CONFIG

if TYPE_CHECKING:
    from src.services.vote import VoteService


def build_vote_metadata_facade(group) -> VoteMetadataFacade:
    session_repo = SqliteSessionRepository(group.db)
    idem_repo = SqliteIdempotencyRepository(group.db, group_id=group.group_id)
    audit_repo = SqliteAuditRepository(group.db)
    vote_repo = SqliteVoteRepository(group.db)
    return VoteMetadataFacade(
        group_id=group.group_id,
        session_repo=session_repo,
        idem_repo=idem_repo,
        audit_repo=audit_repo,
        vote_repo=vote_repo,
    )


def build_governance_manager(service: "VoteService") -> GovernanceManager:
    return GovernanceManager(service, build_vote_metadata_facade(service.group))


__all__ = [
    "GOVERNANCE_DEFAULT_CONFIG",
    "GovernanceManager",
    "build_governance_manager",
    "build_vote_metadata_facade",
]
