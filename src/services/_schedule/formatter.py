from typing import Dict

from .models import TASK_TYPE_NAMES


def format_task_type_name(task_type: str) -> str:
    return TASK_TYPE_NAMES.get(task_type, task_type)


def build_task_summary_message(tasks: Dict[str, Dict]) -> str:
    task_list = []
    for task in tasks.values():
        status = "启用" if task.get("enabled", True) else "禁用"
        task_type = format_task_type_name(task.get("task_type", task.get("type", "")))
        schedule = task.get("schedule", "")
        description = task.get("description", "无描述")
        tool_name = str(task.get("tool_name") or "").strip()
        tool_suffix = f" -> {tool_name}" if tool_name else ""
        task_list.append(f"[{status}] {description}{tool_suffix} ({task_type} {schedule})")
    return f"共 {len(tasks)} 个任务:\n" + "\n".join(task_list)


def build_task_list_message(tasks: Dict[str, Dict]) -> str:
    lines = ["📋【定时任务列表】", ""]
    for index, task in enumerate(tasks.values(), 1):
        status = "✅ 启用" if task.get("enabled", True) else "❌ 禁用"
        task_type = format_task_type_name(task.get("task_type", task.get("type", "")))
        schedule = task.get("schedule", "")
        description = task.get("description", "无描述")
        lines.append(f"{index}. 【{status}】")
        lines.append(f"   📝 {description}")
        lines.append(f"   类型: {task_type} | 时间: {schedule}")
        tool_name = str(task.get("tool_name") or "").strip()
        if tool_name:
            lines.append(f"   工具: {tool_name}")
        lines.append("")
    return "\n".join(lines).rstrip()
