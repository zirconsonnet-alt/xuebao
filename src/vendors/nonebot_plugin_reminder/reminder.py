import re
import json
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Dict, List, TypedDict, Optional, Callable, Union, Any, Coroutine
from nonebot import get_bot
from nonebot.log import logger
from nonebot.adapters.onebot.v11 import Message
from src.support.scheduled_tasks import upsert_scheduler_state_entry
from .exception import SystemExitException
from .tools import wait_for_plus


BEIJING_TIMEZONE = timezone(timedelta(hours=8))


class ReminderTask(TypedDict):
    type: str
    schedule: str
    message: str
    enabled: bool


# 全局回调函数注册表
_callback_registry: Dict[str, Callable[[], Coroutine[Any, Any, None]]] = {}


def register_scheduled_callback(task_id: str, callback: Callable[[], Coroutine[Any, Any, None]]):
    """注册一个定时回调函数

    Args:
        task_id: 任务唯一标识符
        callback: 异步回调函数
    """
    _callback_registry[task_id] = callback
    logger.info(f"已注册定时回调: {task_id}")


def unregister_scheduled_callback(task_id: str):
    """取消注册定时回调函数"""
    if task_id in _callback_registry:
        del _callback_registry[task_id]
        logger.info(f"已取消定时回调: {task_id}")


def get_scheduled_callback(task_id: str) -> Optional[Callable[[], Coroutine[Any, Any, None]]]:
    """获取已注册的回调函数"""
    return _callback_registry.get(task_id)


class ScheduledTaskManager:
    """定时任务管理器 - 管理跨群组的定时任务"""

    def __init__(self):
        self.tasks: Dict[str, Dict] = {}

    def load_tasks(self):
        """数据库已成为调度任务的唯一持久化来源。"""
        return None

    def save_tasks(self):
        """数据库已成为调度任务的唯一持久化来源。"""
        return None

    def add_task(
        self,
        task_id: str,
        task_type: str,
        schedule: str,
        callback_id: str,
        enabled: bool = True,
        group_id: Optional[int] = None,
        description: str = ""
    ) -> bool:
        """添加定时任务

        Args:
            task_id: 任务唯一ID
            task_type: 任务类型 (daily/weekly/once)
            schedule: 时间表达式
            callback_id: 回调函数ID
            enabled: 是否启用
            group_id: 关联的群组ID (可选)
            description: 任务描述
        """
        self.tasks[task_id] = {
            "type": task_type,
            "schedule": schedule,
            "callback_id": callback_id,
            "enabled": enabled,
            "group_id": group_id,
            "description": description
        }
        self.save_tasks()
        logger.info(f"添加定时任务: {task_id} -> {callback_id} @ {schedule}")
        return True

    def remove_task(self, task_id: str) -> bool:
        """移除定时任务"""
        if task_id in self.tasks:
            del self.tasks[task_id]
            self.save_tasks()
            return True
        return False

    def update_task(self, task_id: str, **kwargs) -> bool:
        """更新定时任务配置"""
        if task_id not in self.tasks:
            return False
        for key, value in kwargs.items():
            if value is not None:
                self.tasks[task_id][key] = value
        self.save_tasks()
        return True

    def get_task(self, task_id: str) -> Optional[Dict]:
        """获取任务配置"""
        return self.tasks.get(task_id)

    def get_tasks_by_group(self, group_id: int) -> Dict[str, Dict]:
        """获取特定群组的所有任务"""
        return {
            tid: task for tid, task in self.tasks.items()
            if task.get("group_id") == group_id
        }

    async def check_and_trigger(self):
        """检查并触发到期的任务"""
        now = datetime.now(BEIJING_TIMEZONE)
        current_time = now.strftime("%H:%M")
        current_weekday = str(now.weekday())
        current_fulltime = now.strftime("%Y-%m-%d %H:%M")

        for task_id, task in list(self.tasks.items()):
            if not task.get("enabled", True):
                continue

            task_type = task["type"]
            schedule = task["schedule"]
            triggered = False

            if task_type == "daily" and schedule == current_time:
                triggered = True
            elif task_type == "weekly":
                parts = schedule.split()
                if len(parts) == 2 and parts[0] == current_weekday and parts[1] == current_time:
                    triggered = True
            elif task_type == "once" and schedule == current_fulltime:
                task["enabled"] = False
                upsert_scheduler_state_entry(task_id, task, group_id=task.get("group_id"))
                triggered = True

            if triggered:
                callback_id = task.get("callback_id")
                callback = get_scheduled_callback(callback_id)
                if callback:
                    try:
                        logger.info(f"触发定时任务: {task_id} -> {callback_id}")
                        await callback()
                    except Exception as e:
                        logger.error(f"执行定时任务 {task_id} 失败: {e}")
                else:
                    logger.warning(f"未找到回调函数: {callback_id}")


# 全局定时任务管理器实例
scheduled_task_manager = ScheduledTaskManager()


class ReminderSystem:
    def __init__(
        self,
        user_id: int,
        group_id: int,
        *,
        json_path: Optional[Path | str] = None,
    ):
        self.user_id = int(user_id)
        self.group_id = int(group_id)
        self.tasks: Dict[str, ReminderTask] = {}
        self.json_path = Path(json_path) if json_path is not None else (Path("data") / "reminders.json")
        self.json_path.parent.mkdir(parents=True, exist_ok=True)
        self.special_functions: Dict[str, Callable[[], str]] = {
            "postgraduate_countdown": self.get_postgraduate_countdown
        }
        self.function_descriptions = {
            "postgraduate_countdown": "考研倒计时（自动计算）"
        }
        self.load_tasks()
        self.ensure_default_tasks()
        self.check_expired_tasks()

    async def wait_for(self, timeout: int):
        event = await wait_for_plus(self.user_id, self.group_id, timeout)
        msg = event.get_message().extract_plain_text().strip() if event else ''
        return msg

    @staticmethod
    def get_beijing_time() -> datetime:
        return datetime.now(BEIJING_TIMEZONE)

    async def send(self, msg: Union[Message, str]):
        bot = get_bot()
        try:
            await bot.send_group_msg(group_id=self.group_id, message=msg)
        except Exception as e:
            logger.error(f"发送消息失败: {e}")

    async def handle_input(self, timeout=30, prompt=None):
        if prompt:
            await self.send(prompt)
        response = await self.wait_for(timeout)
        if response == '':
            raise SystemExitException("用户输入为空，退出系统")
        return response

    async def edit_mode(self):
        try:
            while True:
                msg = "📝 提醒任务编辑模式\n" \
                      "1. 添加新任务\n" \
                      "2. 删除任务\n" \
                      "3. 切换任务状态\n" \
                      "4. 查看所有任务\n" \
                      "5. 编辑任务内容\n" \
                      "0. 退出\n" \
                      "请选择操作: "
                choice = await self.handle_input(30, msg)
                if choice == "0":
                    await self.send("已退出编辑模式")
                    return
                elif choice == "1":
                    await self.add_task_interactive()
                elif choice == "2":
                    await self.remove_task_interactive()
                elif choice == "3":
                    await self.toggle_task_interactive()
                elif choice == "4":
                    await self.list_tasks()
                elif choice == "5":
                    await self.edit_task_interactive()
                else:
                    await self.send("无效选择，请重新输入！")
        except SystemExitException:
            await self.send("已退出编辑模式")

    async def list_tasks(self):
        tasks = self.get_all_tasks()
        if not tasks:
            await self.send("当前没有提醒任务")
            return
        msg = "📋 当前提醒任务列表:\n"
        for i, task in enumerate(tasks, 1):
            status = "✅ 启用" if task["enabled"] else "❌ 禁用"
            msg += f"\n{i}. 【{status}】{task['name']}"
            msg += f"\n  类型: {self.get_type_name(task['type'])}"
            msg += f"\n  时间: {task['schedule']}"
            msg += f"\n  内容: {task['message']}\n"
        await self.send(msg)

    def get_type_name(self, task_type):
        return {
            "daily": "每天",
            "weekly": "每周",
            "once": "一次性"
        }.get(task_type, task_type)

    async def add_task_interactive(self):
        try:
            name = await self.handle_input(30, "请输入任务名称: ")
            if not name:
                await self.send("任务名称不能为空!")
                return
            type_choice = await self.handle_input(
                30,
                "请选择任务类型:\n1. 每天重复\n2. 每周重复\n3. 一次性提醒\n请选择(1-3): "
            )
            if type_choice == "1":
                task_type = "daily"
            elif type_choice == "2":
                task_type = "weekly"
            elif type_choice == "3":
                task_type = "once"
            else:
                await self.send("无效选择!")
                return
            time_prompt = {
                "daily": "请输入时间(HH:MM, 如 08:30): ",
                "weekly": "请输入星期(0-6, 0=周一)和时间(HH:MM), 如 '1 08:30': ",
                "once": "请输入日期和时间(YYYY-MM-DD HH:MM, 如 '2023-12-31 23:59'): "
            }[task_type]
            schedule = await self.handle_input(30, time_prompt)
            if not self.validate_schedule(task_type, schedule):
                await self.send("时间格式无效，请重新输入!")
                return
            message = await self.handle_input(30, "请输入提醒内容: ")
            if not message:
                await self.send("提醒内容不能为空!")
                return
            if self.add_task(name, task_type, schedule, message):
                await self.send(f"✅ 任务 '{name}' 添加成功!")
            else:
                await self.send(f"❌ 添加失败! 任务 '{name}' 已存在")
        except SystemExitException:
            await self.send("已取消添加任务")

    async def remove_task_interactive(self):
        tasks = self.get_all_tasks()
        if not tasks:
            await self.send("当前没有提醒任务")
            return
        await self.list_tasks()
        try:
            choice = await self.handle_input(
                30,
                "请输入要删除的任务编号 (输入0取消): "
            )
            if choice == "0":
                return
            if not choice.isdigit() or int(choice) < 1 or int(choice) > len(tasks):
                await self.send("无效的任务编号!")
                return
            task_name = tasks[int(choice) - 1]["name"]
            if self.remove_task(task_name):
                await self.send(f"✅ 任务 '{task_name}' 已删除")
            else:
                await self.send(f"❌ 删除任务 '{task_name}' 失败")
        except SystemExitException:
            await self.send("已取消删除操作")

    async def toggle_task_interactive(self):
        tasks = self.get_all_tasks()
        if not tasks:
            await self.send("当前没有提醒任务")
            return
        await self.list_tasks()
        try:
            choice = await self.handle_input(
                30,
                "请输入要切换状态的任务编号 (输入0取消): "
            )
            if choice == "0":
                return
            if not choice.isdigit() or int(choice) < 1 or int(choice) > len(tasks):
                await self.send("无效的任务编号!")
                return
            task_name = tasks[int(choice) - 1]["name"]
            current_status = self.tasks[task_name]["enabled"]
            new_status = not current_status
            if self.update_task(task_name, enabled=new_status):
                status_text = "启用" if new_status else "禁用"
                await self.send(f"✅ 任务 '{task_name}' 已{status_text}")
            else:
                await self.send(f"❌ 切换任务 '{task_name}' 状态失败")
        except SystemExitException:
            await self.send("已取消切换操作")

    async def edit_task_interactive(self):
        tasks = self.get_all_tasks()
        if not tasks:
            await self.send("当前没有提醒任务")
            return
        await self.list_tasks()
        try:
            choice = await self.handle_input(
                30,
                "请输入要编辑的任务编号 (输入0取消): "
            )
            if choice == "0":
                return
            if not choice.isdigit() or int(choice) < 1 or int(choice) > len(tasks):
                await self.send("无效的任务编号!")
                return
            task_name = tasks[int(choice) - 1]["name"]
            task = self.tasks[task_name]
            await self.send(
                f"📝 编辑任务: {task_name}\n"
                f"当前内容: {task['message']}"
            )
            new_message = await self.handle_input(30, "请输入新的提醒内容: ")
            if not new_message:
                await self.send("提醒内容不能为空!")
                return
            if self.update_task(task_name, message=new_message):
                await self.send(f"✅ 任务 '{task_name}' 内容已更新!")
            else:
                await self.send(f"❌ 更新任务 '{task_name}' 内容失败")
        except SystemExitException:
            await self.send("已取消编辑操作")

    def ensure_default_tasks(self):
        default_tasks = {
            "考研倒计时": {
                "type": "daily",
                "schedule": "08:00",
                "message": "func:postgraduate_countdown",
                "enabled": True
            },
            "睡前刷牙": {
                "type": "daily",
                "schedule": "23:50",
                "message": "🦷 刷牙时间到！请用电动牙刷仔细清洁牙齿2分钟",
                "enabled": True
            },
            "睡前补充": {
                "type": "daily",
                "schedule": "00:00",
                "message": "💤 睡前补充时间！请服用：\n1颗褪黑素软糖\n2颗伽马氨基丁酸糖果",
                "enabled": True
            }
        }
        updated = False
        for name, task in default_tasks.items():
            if name not in self.tasks:
                self.tasks[name] = task
                updated = True
        if updated:
            self.save_tasks()

    def load_tasks(self):
        try:
            if self.json_path.exists():
                with open(self.json_path, 'r', encoding='utf-8') as f:
                    raw_tasks = json.load(f)
                    self.tasks = {}
                    for name, task in raw_tasks.items():
                        if "type" not in task:
                            task["type"] = "daily"
                            task["schedule"] = task.pop("time", "00:00")
                        self.tasks[name] = task
                logger.info(f"成功加载 {len(self.tasks)} 个提醒任务")
            else:
                self.tasks = {}
                logger.info("未找到提醒任务文件，将创建新文件")
        except Exception as e:
            logger.error(f"加载提醒任务失败: {e}")
            self.tasks = {}

    def check_expired_tasks(self):
        now = self.get_beijing_time()
        updated = False
        for name, task in list(self.tasks.items()):
            if task["type"] == "once" and task["enabled"]:
                try:
                    task_time = datetime.strptime(task["schedule"], "%Y-%m-%d %H:%M")
                    task_time = task_time.replace(tzinfo=BEIJING_TIMEZONE)
                    if task_time < now:
                        task["enabled"] = False
                        updated = True
                        logger.info(f"已禁用过期任务: {name}")
                except ValueError:
                    logger.error(f"一次性任务时间格式错误: {name} - {task['schedule']}")
                    task["enabled"] = False
                    updated = True
        if updated:
            self.save_tasks()

    def save_tasks(self):
        try:
            with open(self.json_path, 'w', encoding='utf-8') as f:
                json.dump(self.tasks, f, ensure_ascii=False, indent=2)
            logger.info(f"成功保存 {len(self.tasks)} 个提醒任务")
            return True
        except Exception as e:
            logger.error(f"保存提醒任务失败: {e}")
            return False

    def validate_schedule(self, task_type: str, schedule: str) -> bool:
        if task_type == "daily":
            return bool(re.match(r"^([0-1]?[0-9]|2[0-3]):[0-5][0-9]$", schedule))
        elif task_type == "weekly":
            parts = schedule.split()
            if len(parts) != 2:
                return False
            weekday, time_str = parts
            return weekday.isdigit() and 0 <= int(weekday) <= 6 and \
                bool(re.match(r"^([0-1]?[0-9]|2[0-3]):[0-5][0-9]$", time_str))
        elif task_type == "once":
            try:
                datetime.strptime(schedule, "%Y-%m-%d %H:%M")
                return True
            except ValueError:
                return False
        return False

    def add_task(self, name: str, task_type: str, schedule: str, message: str, enabled: bool = True) -> bool:
        if name in self.tasks:
            return False
        if not self.validate_schedule(task_type, schedule):
            return False
        self.tasks[name] = {
            "type": task_type,
            "schedule": schedule,
            "message": message,
            "enabled": enabled
        }
        return self.save_tasks()

    def remove_task(self, name: str) -> bool:
        if name not in self.tasks:
            return False
        del self.tasks[name]
        return self.save_tasks()

    def update_task(
            self, name: str, task_type: Optional[str] = None,
            schedule: Optional[str] = None, message: Optional[str] = None,
            enabled: Optional[bool] = None
    ) -> bool:
        if name not in self.tasks:
            return False
        task = self.tasks[name]
        if task_type is not None:
            current_schedule = schedule if schedule is not None else task["schedule"]
            if not self.validate_schedule(task_type, current_schedule):
                return False
            task["type"] = task_type
            task["schedule"] = current_schedule
        if schedule is not None:
            if not self.validate_schedule(task["type"], schedule):
                return False
            task["schedule"] = schedule
        if message is not None:
            task["message"] = message
        if enabled is not None:
            task["enabled"] = enabled
        return self.save_tasks()

    def get_all_tasks(self) -> List[dict]:
        formatted_tasks = []
        for name, task in self.tasks.items():
            message = task["message"]
            if message.startswith("func:"):
                func_name = message[5:]
                description = self.function_descriptions.get(func_name, "特殊函数")
                message = f"⚙️ {description}"
            formatted_tasks.append({
                "name": name,
                "type": task["type"],
                "schedule": task["schedule"],
                "message": message,
                "enabled": task["enabled"]
            })
        return formatted_tasks

    def get_postgraduate_countdown(self) -> str:
        exam_date = datetime(2025, 12, 20, tzinfo=BEIJING_TIMEZONE)
        today = self.get_beijing_time()
        delta = exam_date - today
        days = delta.days
        if days > 30:
            status = "⏳"
        elif days > 7:
            status = "🚀"
        else:
            status = "🔥"
        return f"{status} 距离考研初试(2025-12-20)还有{days}天\n保持专注，继续努力！"

    async def check_and_trigger(self):
        now = self.get_beijing_time()
        current_time = now.strftime("%H:%M")
        current_weekday = str(now.weekday())
        current_fulltime = now.strftime("%Y-%m-%d %H:%M")
        logger.info(f"北京时间检查提醒: {current_fulltime} {current_time} 星期{current_weekday}")
        for task_name, task in self.tasks.items():
            if not task["enabled"]:
                continue
            task_type = task["type"]
            schedule = task["schedule"]
            triggered = False
            if task_type == "daily" and schedule == current_time:
                triggered = True
            elif task_type == "weekly":
                parts = schedule.split()
                if len(parts) == 2 and parts[0] == current_weekday and parts[1] == current_time:
                    triggered = True
            elif task_type == "once" and schedule == current_fulltime:
                task["enabled"] = False
                self.save_tasks()
                triggered = True
            if triggered:
                logger.info(f"触发提醒: {task_name} - {schedule}")
                await self.trigger_reminder(task_name)
            else:
                logger.debug(f"未触发: {task_name} - {schedule}")

    async def trigger_reminder(self, task_name: str):
        if task_name not in self.tasks:
            logger.warning(f"尝试触发不存在的任务: {task_name}")
            return
        task = self.tasks[task_name]
        message = task["message"]
        if message.startswith("func:"):
            func_name = message[5:]
            if func_name in self.special_functions:
                message = self.special_functions[func_name]()
            else:
                logger.error(f"未知的特殊函数: {func_name}")
                message = f"⚠️ 提醒任务 '{task_name}' 配置错误"
        current_time = self.get_beijing_time().strftime("%H:%M")
        formatted_message = f"⏰ [{current_time}] {message}"
        await self.send_reminder(formatted_message)

    async def send_reminder(self, message: str):
        bot = get_bot()
        try:
            await bot.send_group_msg(group_id=self.group_id, message=message)
            logger.info(f"已发送提醒消息: {message}")
        except Exception as e:
            logger.error(f"发送提醒消息失败: {e}")
