import traceback
from typing import TYPE_CHECKING

from arclet.alconna import Alconna
from nonebot.adapters.onebot.v11 import GroupMessageEvent
from nonebot_plugin_alconna import on_alconna

from .manager import VoteManager
from .metadata import (
    VoteMetadataFacade,
    _build_idempotency_key,
    _build_session_key,
    _record_side_effect_audit,
    _reserve_side_effect,
)
from .runtime import _collect_topic, _get_vote_duration, build_vote_handler, wait_for_condition
from .strategies import BanStrategy, KickStrategy, SetStrategy, Strategy, TopicStrategy
from .use_cases import AwardHonorForTopicVoteUseCase, CreateTopicAndChargeUseCase

if TYPE_CHECKING:
    from src.support.group import GroupContext


class VoteController:
    def __init__(self, group: "GroupContext", strategy: Strategy, metadata: VoteMetadataFacade):
        self.group = group
        self.strategy = strategy
        self.vote_manager = VoteManager()
        self.metadata = metadata

    async def vote(self, event: GroupMessageEvent):
        session_key = _build_session_key(self.group.group_id, "vote_active", "group")
        self.vote_manager.configure_session(vote_repo=self.metadata.vote_repo, session_key=session_key)
        try:
            self.metadata.cleanup_expired_sessions()
            existing = self.metadata.get_session(session_key)
            if existing and existing.is_active():
                await self.group.send_msg("本群已有投票活动正在进行！")
                return

            idempotency_key = _build_idempotency_key(event, "vote_start", session_key)
            if self.group.is_voting:
                await self.group.send_msg("本群已有投票活动正在进行！")
                return

            if not self.metadata.start_vote_session(
                actor_id=event.user_id,
                session_key=session_key,
                flow="vote_create",
                ttl_seconds=600,
                idempotency_key=idempotency_key,
                initial_data={"strategy": self.strategy.__class__.__name__},
                audit_context={"strategy": self.strategy.__class__.__name__},
            ):
                return
            self.start_vote()
            topic = await _collect_topic(self.strategy, self.group, event, self.vote_manager)
            if not topic:
                self.metadata.cancel_session(session_key)
                self.end_vote()
                return

            if isinstance(self.strategy, TopicStrategy):
                use_case = CreateTopicAndChargeUseCase(cost_points=0)
                eco = use_case.execute(
                    db=self.group.db,
                    group_id=self.group.group_id,
                    user_id=event.user_id,
                    content=str(topic.get("content") or ""),
                )
                if eco.topic_id is None:
                    await self.group.send_msg("❌ 议题创建失败，请稍后重试。")
                    self.metadata.cancel_session(session_key)
                    self.end_vote()
                    return
                topic["topic_id"] = eco.topic_id
                if eco.created:
                    await self.group.send_msg(f"✅ 议题已创建（ID: {eco.topic_id}）。")
                else:
                    await self.group.send_msg(f"ℹ️ 已存在相同议题创建记录（ID: {eco.topic_id}）。")

            session = self.metadata.get_session(session_key)
            if session:
                self.metadata.update_session_step(
                    session_key=session_key,
                    step=1,
                    patch_data={"topic": topic},
                    expected_version=session.version,
                )

            topic["user_id"] = event.user_id
            topic["session_key"] = session_key
            vote_time = await _get_vote_duration(self.group)
            if not vote_time:
                self.metadata.cancel_session(session_key)
                self.end_vote()
                return

            session = self.metadata.get_session(session_key)
            if session:
                self.metadata.update_session_step(
                    session_key=session_key,
                    step=2,
                    patch_data={"vote_time": vote_time},
                    expected_version=session.version,
                    ttl_seconds=vote_time + 300,
                )

            prompt = self.strategy.get_vote_prompt(self.vote_manager, topic, vote_time)
            await self.group.send_msg(prompt)
            matcher = on_alconna(Alconna(r"re:^\d+$"))

            on_vote_success = None
            if isinstance(self.strategy, TopicStrategy) and topic.get("topic_id"):
                topic_id = int(topic["topic_id"])

                def _award(_user_id: int, _choice: int) -> bool:
                    use_case = AwardHonorForTopicVoteUseCase(honor_per_vote=1)
                    result = use_case.execute(
                        db=self.group.db,
                        group_id=self.group.group_id,
                        user_id=_user_id,
                        topic_id=topic_id,
                        choice=_choice,
                    )
                    return result.awarded

                on_vote_success = _award

            matcher.append_handler(build_vote_handler(self.vote_manager, self.group, on_vote_success=on_vote_success))
            await wait_for_condition(
                lambda: len(self.vote_manager.voted_users) < self.strategy.get_full(),
                vote_time,
            )

            side_effect_applied = None
            if isinstance(self.strategy, TopicStrategy) and self.strategy.passed(self.vote_manager):
                if _reserve_side_effect(
                    self.metadata,
                    action="topic_notice_apply",
                    session_key=topic.get("session_key"),
                    actor_id=topic.get("user_id"),
                    subject_type="topic",
                    subject_id=topic.get("content"),
                ):
                    await self.group.process_group_notice(
                        topic["content"],
                        topic["user_id"],
                        self.vote_manager.voted_users,
                    )
                    _record_side_effect_audit(
                        self.metadata,
                        actor_id=topic.get("user_id"),
                        action="topic_notice_apply",
                        session_key=topic.get("session_key"),
                        subject_type="topic",
                        subject_id=topic.get("content"),
                        result="success",
                        context={"voters": len(self.vote_manager.voted_users)},
                    )
                    side_effect_applied = True
                else:
                    side_effect_applied = False

            if isinstance(self.strategy, SetStrategy) and self.strategy.passed(self.vote_manager):
                if _reserve_side_effect(
                    self.metadata,
                    action="set_essence",
                    session_key=topic.get("session_key"),
                    actor_id=topic.get("user_id"),
                    subject_type="message",
                    subject_id=str(topic.get("content")),
                ):
                    await self.group.set_msg(topic["content"])
                    _record_side_effect_audit(
                        self.metadata,
                        actor_id=topic.get("user_id"),
                        action="set_essence",
                        session_key=topic.get("session_key"),
                        subject_type="message",
                        subject_id=str(topic.get("content")),
                        result="success",
                        context={"voters": len(self.vote_manager.voted_users)},
                    )
                    side_effect_applied = True
                else:
                    side_effect_applied = False

            if isinstance(self.strategy, BanStrategy) and self.strategy.passed(self.vote_manager):
                if _reserve_side_effect(
                    self.metadata,
                    action="ban_user",
                    session_key=topic.get("session_key"),
                    actor_id=topic.get("user_id"),
                    subject_type="user",
                    subject_id=str(topic.get("content")),
                ):
                    await self.group.ban(topic["content"], 3600)
                    _record_side_effect_audit(
                        self.metadata,
                        actor_id=topic.get("user_id"),
                        action="ban_user",
                        session_key=topic.get("session_key"),
                        subject_type="user",
                        subject_id=str(topic.get("content")),
                        result="success",
                        context={"duration": 3600},
                    )
                    side_effect_applied = True
                else:
                    side_effect_applied = False

            if isinstance(self.strategy, KickStrategy) and self.strategy.passed(self.vote_manager):
                if _reserve_side_effect(
                    self.metadata,
                    action="kick_user",
                    session_key=topic.get("session_key"),
                    actor_id=topic.get("user_id"),
                    subject_type="user",
                    subject_id=str(topic.get("content")),
                ):
                    await self.group.kick(topic["content"])
                    _record_side_effect_audit(
                        self.metadata,
                        actor_id=topic.get("user_id"),
                        action="kick_user",
                        session_key=topic.get("session_key"),
                        subject_type="user",
                        subject_id=str(topic.get("content")),
                        result="success",
                        context={},
                    )
                    side_effect_applied = True
                else:
                    side_effect_applied = False

            result = self.strategy.result_text(
                self.vote_manager,
                topic,
                side_effect_applied=side_effect_applied,
            )
            await matcher.send(result)
            matcher.destroy()
            self.metadata.finish_vote_session(
                actor_id=event.user_id,
                session_key=session_key,
                audit_context={
                    "strategy": self.strategy.__class__.__name__,
                    "voters": len(self.vote_manager.voted_users),
                    "options": self.vote_manager.get_results(),
                },
            )
        except Exception as exc:
            traceback.print_exc()
            print(exc)
            self.metadata.record_audit_event(
                actor_id=event.user_id,
                action="vote_error",
                subject_type="vote",
                subject_id=session_key,
                session_key=session_key,
                result="failure",
                context={"error": str(exc)},
            )
        finally:
            self.end_vote()

    def start_vote(self):
        self.group.set_voting(True)

    def end_vote(self):
        self.group.set_voting(False)
