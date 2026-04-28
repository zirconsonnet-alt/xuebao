import httpx
import nonebot
from pathlib import Path
from pytz import timezone
from typing import Union, List, Tuple, Optional
from datetime import datetime, timedelta
from nonebot.adapters.onebot.v11 import Message, MessageSegment
from src.vendors.nonebot_plugin_reminder.tools import wait_for_plus
from src.vendors.nonebot_plugin_reminder.exception import SystemExitException


PLAN_START_DATE = datetime(2025, 7, 3).date()


class Viewer:
    def __init__(
        self,
        user_id: int = 3125049051,
        group_id: int = 1049391740,
        *,
        root_dir: Optional[Path | str] = None,
        goals_file: Optional[Path | str] = None,
    ):
        root_path = Path(root_dir) if root_dir is not None else (Path("data") / "viewer")
        self.data = root_path / "tasks"
        self.goals_file = Path(goals_file) if goals_file is not None else (root_path / "goals.txt")
        self.data.mkdir(parents=True, exist_ok=True)
        self.user_id = int(user_id)
        self.group_id = int(group_id)
        self.math_indices = [1, 5]
        self.cs_indices = [2, 3, 4, 6]
        self.today = datetime.now(timezone('Asia/Shanghai')).date()
        self.tasks: List[str] = []
        self._refresh_tasks()

    def _refresh_tasks(self):
        self.today = datetime.now(timezone('Asia/Shanghai')).date()
        self.tasks = []
        if self.today < PLAN_START_DATE:
            return

        date_range = [
            PLAN_START_DATE + timedelta(days=i)
            for i in range((self.today - PLAN_START_DATE).days + 1)
        ]
        for date in date_range:
            for index in range(1, 7):
                task_id = f"{date.strftime('%Y-%m-%d')}-{index}"
                self.tasks.append(task_id)
                task_dir = self.data / task_id
                task_dir.mkdir(exist_ok=True)
                screenshots_dir = task_dir / "screen_shots"
                screenshots_dir.mkdir(exist_ok=True)
                progress_file = task_dir / "progress.txt"
                if not progress_file.exists():
                    progress_file.touch()

    async def handle_input(self, timeout=30, prompt=None):
        if prompt:
            await self.send(prompt)
        response = await self.wait_for(timeout)
        if response is None:
            raise SystemExitException("用户输入为空，退出系统")
        return response

    async def handler_task(self, index):
        self._refresh_tasks()
        task_ids = self.get_tasks_by_index(index)
        for task_id in task_ids:
            task_dir = self.data / task_id
            await self.send(f"❓ {task_id}留下的问题：")
            question_img = task_dir / "question.jpg"
            if question_img.exists():
                await self.send(MessageSegment.image(question_img))
            else:
                await self.send("✅ 未找到问题描述图片")
            screenshots_dir = task_dir / "screen_shots"
            screenshot_files = []
            if screenshots_dir.exists():
                for file in screenshots_dir.iterdir():
                    if file.is_file() and file.suffix.lower() in ['.jpg', '.png', '.jpeg']:
                        screenshot_files.append(file)
                screenshot_files.sort()
            if screenshot_files:
                await self.send(f"💯 {task_id}留下的回放：")
                for file in screenshot_files:
                    await self.send(MessageSegment.image(file))
            else:
                await self.send("✅ 未找到回放")
            progress_file = task_dir / "progress.txt"
            if progress_file.exists():
                with open(progress_file, 'r', encoding='utf-8') as f:
                    progress = f.read().strip()
                if progress:
                    await self.send(f"📊 本次学习进度：\n{progress}")
                else:
                    await self.send("📊 本次学习进度：暂无记录")
            else:
                await self.send("📊 本次学习进度：暂无记录")
            prev_progress = self.get_previous_progress(task_id, index)
            if prev_progress:
                prev_task_id, prev_content = prev_progress
                await self.send(f"📊 上一次同类型学习周期（{prev_task_id}）的进度：\n{prev_content}")
            else:
                await self.send("📊 没有找到上一次同类型学习周期的记录")
            goal_progress = self.get_goal_progress(task_id, index)
            if goal_progress:
                await self.send(goal_progress)

    def get_tasks_by_index(self, index: int) -> List[str]:
        if not 1 <= index <= 6:
            raise ValueError("序号必须在1-6范围内")
        filtered_tasks = [task for task in self.tasks if task.endswith(f"-{index}")]

        def extract_date(task_id: str) -> datetime:
            date_part = '-'.join(task_id.split('-')[:3])
            return datetime.strptime(date_part, "%Y-%m-%d")
        filtered_tasks.sort(key=extract_date, reverse=True)
        return filtered_tasks

    async def download_image_from_segment(self, segment, save_path: Path):
        url = segment.data.get('url') or segment.data.get('file')
        if url:
            await self.download_image(url, save_path)
            return True
        return False

    async def download_images_from_message(
            self,
            message,
            save_dir: Path,
            filename_pattern: str = "image_{index}.jpg",
            max_count: int = None
    ) -> int:
        count = 0
        for segment in message:
            if max_count is not None and count >= max_count:
                break
            if segment.type == 'image':
                filename = filename_pattern.format(index=count)
                success = await self.download_image_from_segment(
                    segment,
                    save_dir / filename
                )
                if success:
                    count += 1
        return count

    async def collect_question_and_screenshots(self, index: int):
        self._refresh_tasks()
        if self.today < PLAN_START_DATE:
            await self.send(f"❌ 计划从 {PLAN_START_DATE} 开始，当前日期过早")
            return
        try:
            today = datetime.now(timezone('Asia/Shanghai')).date()
            task_id = f"{today.strftime('%Y-%m-%d')}-{index}"
            task_dir = self.data / task_id
            screenshots_dir = task_dir / "screen_shots"
            task_dir.mkdir(exist_ok=True, parents=True)
            screenshots_dir.mkdir(exist_ok=True)
            await self.send("📝 请发送问题")
            try:
                event = await self.handle_input(120)
            except SystemExitException:
                await self.send('❌ 系统已退出')
                return
            saved_count = await self.download_images_from_message(
                event.get_message(),
                save_dir=task_dir,
                filename_pattern="question.jpg",
                max_count=1
            )
            if not saved_count:
                await self.send("❌ 未收到问题，已退出")
                return
            await self.send("📝 问题已保存，请发送回放（输入0结束）")
            total_screenshots = 0
            while True:
                try:
                    event = await self.handle_input(60)
                except SystemExitException:
                    await self.send('❌ 系统已退出')
                    return
                msg = event.get_message()
                if msg.extract_plain_text().strip() == '0':
                    await self.send("✅ 结束收集回放")
                    break
                count = await self.download_images_from_message(
                    msg,
                    save_dir=screenshots_dir,
                    filename_pattern="screenshot_{index}.jpg"
                )
                if count > 0:
                    total_screenshots += count
                else:
                    await self.send("📝 请发送回放或输入0结束")
            await self.send("📝 请发送本次学习周期的进度描述")
            try:
                progress_event = await self.handle_input(120)
            except SystemExitException:
                await self.send('❌ 系统已退出')
                return
            progress_text = progress_event.get_message().extract_plain_text().strip()
            progress_file = task_dir / "progress.txt"
            with open(progress_file, 'w', encoding='utf-8') as f:
                f.write(progress_text)
            await self.send(f"✅ 共保存了{total_screenshots}张回放和进度描述")
        except SystemExitException:
            await self.send("❌ 已退出问题收集")
        except Exception as e:
            await self.send(f"❌ 处理过程中出错: {str(e)}")

    @staticmethod
    async def download_image(url: str, save_path: Path):
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            if response.status_code == 200:
                with open(save_path, 'wb') as f:
                    f.write(response.content)
                return True
        return False

    async def wait_for(self, timeout: int):
        return await wait_for_plus(self.user_id, self.group_id, timeout)

    async def send(self, msg: Union[Message, MessageSegment, str]):
        await nonebot.get_bot().send_group_msg(
            group_id=self.group_id,
            message=msg
        )

    def get_previous_progress(self, current_task_id: str, current_index: int) -> Union[Tuple[str, str], None]:
        task_type = "math" if current_index in self.math_indices else "cs"
        current_date = datetime.strptime('-'.join(current_task_id.split('-')[:3]), "%Y-%m-%d").date()
        same_type_indices = self.math_indices if task_type == "math" else self.cs_indices
        same_type_tasks = []
        for task in self.tasks:
            task_index = int(task.split('-')[-1])
            task_date = datetime.strptime('-'.join(task.split('-')[:3]), "%Y-%m-%d").date()
            if task_index in same_type_indices and task_date < current_date:
                same_type_tasks.append((task_date, task))
        if not same_type_tasks:
            return None
        same_type_tasks.sort(key=lambda x: x[0], reverse=True)
        _, most_recent_task_id = same_type_tasks[0]
        progress_file = self.data / most_recent_task_id / "progress.txt"
        if progress_file.exists():
            with open(progress_file, 'r', encoding='utf-8') as f:
                content = f.read().strip()
            return most_recent_task_id, content if content else "暂无进度记录"
        return most_recent_task_id, "无进度文件"

    def get_goal_progress(self, task_id: str, index: int) -> str:
        if not self.goals_file.exists():
            return "暂无目标信息"
        task_type = "math" if index in self.math_indices else "cs"
        task_date = datetime.strptime('-'.join(task_id.split('-')[:3]), "%Y-%m-%d").date()
        goals = []
        with open(self.goals_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split('|')
                if len(parts) < 6:
                    continue
                g_type, start_date_str, start_idx, end_date_str, end_idx, desc = parts[:6]
                try:
                    start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
                    start_idx = int(start_idx)
                    end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
                    end_idx = int(end_idx)
                except ValueError:
                    continue
                goals.append((g_type, start_date, start_idx, end_date, end_idx, desc))
        relevant_goals = []
        for goal in goals:
            g_type, start_date, start_idx, end_date, end_idx, desc = goal
            if g_type != task_type:
                continue
            if end_date < task_date:
                continue
            relevant_goals.append(goal)
        if not relevant_goals:
            return "没有进行中的目标"
        progress_msgs = []
        for goal in relevant_goals:
            g_type, start_date, start_idx, end_date, end_idx, desc = goal
            total_cycles = self.calculate_cycles_in_range(
                start_date, end_date,
                self.math_indices if g_type == "math" else self.cs_indices
            )
            used_cycles = self.calculate_cycles_in_range(
                start_date, self.today,
                self.math_indices if g_type == "math" else self.cs_indices
            )
            progress_percent = (used_cycles / total_cycles * 100) if total_cycles > 0 else 0
            progress_msgs.append(
                f"目标: {desc}\n"
                f"进度: {used_cycles}/{total_cycles} ({progress_percent:.1f}%)\n"
                f"时间范围: {start_date}到{end_date}"
            )
        return "当前目标进度:\n" + "\n\n".join(progress_msgs)

    @staticmethod
    def calculate_cycles_in_range(start_date: datetime.date, end_date: datetime.date, indices: List[int]) -> int:
        if end_date < start_date:
            return 0
        total_days = (end_date - start_date).days + 1
        total_cycles = 0
        for i in range(total_days):
            current_date = start_date + timedelta(days=i)
            if current_date < PLAN_START_DATE:
                continue
            for idx in range(1, 7):
                if idx in indices:
                    total_cycles += 1
        return total_cycles

    def save_goal(self, goal_type: str, start_date: str, start_idx: int, end_date: str, end_idx: int, description: str):
        goal_line = f"{goal_type}|{start_date}|{start_idx}|{end_date}|{end_idx}|{description}"
        if not self.goals_file.exists():
            self.goals_file.parent.mkdir(parents=True, exist_ok=True)
            self.goals_file.touch()
        with open(self.goals_file, 'a', encoding='utf-8') as f:
            f.write(goal_line + "\n")
