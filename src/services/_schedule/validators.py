import re
from datetime import datetime


def validate_schedule(task_type: str, schedule: str) -> bool:
    if task_type == "daily":
        return bool(re.match(r"^([0-1]?[0-9]|2[0-3]):[0-5][0-9]$", schedule))
    if task_type == "weekly":
        parts = schedule.split()
        if len(parts) != 2:
            return False
        weekday, time_str = parts
        return weekday.isdigit() and 0 <= int(weekday) <= 6 and bool(
            re.match(r"^([0-1]?[0-9]|2[0-3]):[0-5][0-9]$", time_str)
        )
    if task_type == "once":
        try:
            datetime.strptime(schedule, "%Y-%m-%d %H:%M")
            return True
        except ValueError:
            return False
    return False
