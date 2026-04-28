"""积分相关的轻量辅助函数。"""

from typing import Any


def normalize_points_cost(raw_value: Any) -> int:
    try:
        return max(0, int(raw_value or 0))
    except (TypeError, ValueError):
        return 0


def format_points_insufficient_message(
    *,
    required_points: int,
    current_balance: int,
    action_label: str,
    custom_message: str = "",
) -> str:
    normalized_label = str(action_label or "当前操作").strip() or "当前操作"
    normalized_required = max(0, int(required_points or 0))
    normalized_balance = int(current_balance or 0)
    template = str(custom_message or "").strip()
    if template:
        try:
            return template.format(
                action_label=normalized_label,
                required_points=normalized_required,
                current_balance=normalized_balance,
            )
        except Exception:
            return template

    return (
        f"❌ 积分不足，无法执行「{normalized_label}」。\n"
        f"当前积分：{normalized_balance}\n"
        f"所需积分：{normalized_required}\n"
        "提示：可以先发送“签到”获取积分。"
    )


__all__ = ["format_points_insufficient_message", "normalize_points_cost"]
