from dataclasses import dataclass
from datetime import datetime
import random
from typing import Callable

from nonebot.adapters.onebot.v11 import GroupMessageEvent

from src.services.base import BaseService, config_property, service_action
from src.support.core import Services


@dataclass(frozen=True)
class SignInResult:
    sign_date: str
    signed_in: bool
    awarded_points: int
    points_balance: int


def sample_sign_in_points() -> int:
    sampled_value = random.gauss(10, 4)
    return max(1, min(50, int(round(sampled_value))))


class SignInUseCase:
    def __init__(self, *, points_sampler: Callable[[], int] | None = None):
        self._points_sampler = points_sampler or sample_sign_in_points

    def execute(
        self,
        *,
        db,
        group_id: int,
        user_id: int,
        now: datetime | None = None,
    ) -> SignInResult:
        local_now = now or datetime.now()
        sign_date = local_now.date().isoformat()
        awarded_points = 0

        reserved = db.reserve_sign_in(user_id=user_id, sign_date=sign_date)
        if reserved:
            awarded_points = max(0, int(self._points_sampler() or 0))
            idem_key = f"sign_in:{group_id}:{user_id}:{sign_date}"
            db.insert_ledger(
                user_id=user_id,
                currency="points",
                delta=awarded_points,
                reason="sign_in",
                ref_type="sign_in",
                ref_id=sign_date,
                idempotency_key=idem_key,
            )

        points_balance = db.get_balance(user_id=user_id, currency="points")
        return SignInResult(
            sign_date=sign_date,
            signed_in=reserved,
            awarded_points=awarded_points,
            points_balance=points_balance,
        )


class SignInService(BaseService):
    service_type = Services.SignIn
    default_config = {
        "enabled": True,
    }

    enabled = config_property("enabled")

    @service_action(cmd="签到", desc="每日签到获得积分")
    async def sign_in(self, event: GroupMessageEvent):
        if not self.enabled:
            await self.group.send_msg("🚫 本群签到服务未开启。可发送“开启签到服务”开启。")
            return

        use_case = SignInUseCase()
        result = use_case.execute(
            db=self.group.db,
            group_id=self.group.group_id,
            user_id=event.user_id,
            now=datetime.now(),
        )

        if result.signed_in:
            await self.group.send_msg(
                f"✅ 签到成功！({result.sign_date})\n"
                f"获得积分：{result.awarded_points}\n"
                f"当前积分：{result.points_balance}"
            )
            return

        await self.group.send_msg(
            f"ℹ️ 你今天已经签到过了。({result.sign_date})\n"
            f"当前积分：{result.points_balance}"
        )

__all__ = ["SignInResult", "SignInUseCase", "SignInService", "sample_sign_in_points"]
