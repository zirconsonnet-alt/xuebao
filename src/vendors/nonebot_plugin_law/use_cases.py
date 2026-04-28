from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from src.support.core import Activities, GroupGateway, MemberStatsRepository, TopicRepository


@dataclass(frozen=True)
class CreateTopicAndChargeResult:
    created: bool
    topic_id: Optional[int]
    points_balance: int
    sign_date: str


class CreateTopicAndChargeUseCase:
    def __init__(self, *, cost_points: int = 5):
        self._cost_points = int(cost_points)

    def execute(
        self,
        *,
        db,
        group_id: int,
        user_id: int,
        content: str,
        now: datetime | None = None,
    ) -> CreateTopicAndChargeResult:
        local_now = now or datetime.now()
        sign_date = local_now.date().isoformat()

        created, topic_id, balance = db.create_topic_and_charge(
            user_id=user_id,
            content=content,
            sign_date=sign_date,
            cost_points=self._cost_points,
        )
        return CreateTopicAndChargeResult(
            created=created,
            topic_id=topic_id,
            points_balance=balance,
            sign_date=sign_date,
        )


@dataclass(frozen=True)
class AwardHonorForTopicVoteResult:
    awarded: bool
    honor_balance: int


class AwardHonorForTopicVoteUseCase:
    def __init__(self, *, honor_per_vote: int = 1):
        self._honor_per_vote = int(honor_per_vote)

    def execute(
        self,
        *,
        db,
        group_id: int,
        user_id: int,
        topic_id: int,
        choice: int,
        now: datetime | None = None,
    ) -> AwardHonorForTopicVoteResult:
        _ = now or datetime.now()

        reserved = db.reserve_topic_vote(
            user_id=user_id,
            topic_id=int(topic_id),
            choice=int(choice),
        )
        if reserved:
            idem_key = f"honor:topic_vote:{group_id}:{topic_id}:{user_id}"
            db.insert_ledger(
                user_id=user_id,
                currency="honor",
                delta=self._honor_per_vote,
                reason="topic_vote_participation",
                ref_type="topic",
                ref_id=str(topic_id),
                idempotency_key=idem_key,
            )

        honor_balance = db.get_balance(user_id=user_id, currency="honor")
        return AwardHonorForTopicVoteResult(awarded=reserved, honor_balance=honor_balance)


class ApproveTopicAndRefreshNoticeUseCase:
    def __init__(
        self,
        *,
        topic_repo: TopicRepository,
        member_stats_repo: MemberStatsRepository,
        group_gateway: GroupGateway,
    ):
        self.topic_repo = topic_repo
        self.member_stats_repo = member_stats_repo
        self.group_gateway = group_gateway

    async def execute(
        self,
        *,
        group_id: int,
        proposer_id: int,
        content: str,
        joiners: List[int],
    ) -> int:
        topic_id = self.topic_repo.add_topic(proposer_id, content)
        for joiner_id in joiners:
            self.member_stats_repo.update_member_stats(joiner_id, Activities.VOTED_TOPICS)
        self.topic_repo.record_supporters(topic_id, joiners)

        all_topics = self.topic_repo.get_all_topics()
        notice_lines = ["本群已通过以下议题："]
        for idx, topic in enumerate(all_topics, start=1):
            notice_lines.append(f"{idx}. {topic['content']}")
        notice_content = "\n".join(notice_lines)

        res = await self.group_gateway.get_notice(group_id)
        notice_id = None
        for notice in res:
            if notice["message"]["text"].startswith("本群已通过以下议题："):
                notice_id = notice["notice_id"]
                break
        if notice_id:
            await self.group_gateway.del_notice(group_id, notice_id)
        if len(all_topics) > 0:
            await self.group_gateway.send_notice(group_id, notice_content)
        else:
            await self.group_gateway.send_notice(group_id, "当前暂无已通过议题")
        return topic_id
