import os
import re
import uuid
from pprint import pprint

import aiohttp
from nonebot.adapters.onebot.v11.event import File

from src.support.core import Services
from src.support.group import run_flow, wait_for, wait_for_event
from src.support.scheduled_tasks import (
    get_runtime_task,
    register_runtime_callback,
    upsert_runtime_task,
)

from .base import BaseService, config_property, service_action


class FileService(BaseService):
    service_type = Services.File
    enable_requires_bot_admin = True
    _TASK_STATE_SCOPE = "scheduler"
    default_config = {
        "enabled": False,
        "auto_move": True,
        "check_illegal": True,
        "background": None,
        "auto_organize_enabled": False,
        "auto_organize_time": "04:00",
        "auto_arrange_enabled": False,
        "auto_arrange_time": "05:00",
    }
    enabled = config_property("enabled")
    auto_move = config_property("auto_move")
    check_illegal = config_property("check_illegal")
    background = config_property("background")
    auto_organize_enabled = config_property("auto_organize_enabled")
    auto_organize_time = config_property("auto_organize_time")
    auto_arrange_enabled = config_property("auto_arrange_enabled")
    auto_arrange_time = config_property("auto_arrange_time")

    def _task_state_key(self, task_name: str) -> str:
        return task_name

    def _build_task_state(
        self,
        *,
        task_id: str,
        schedule: str,
        callback_id: str,
        description: str,
        enabled: bool,
    ) -> dict:
        return {
            "task_id": task_id,
            "task_type": "daily",
            "schedule": schedule,
            "callback_id": callback_id,
            "enabled": enabled,
            "group_id": self.group.group_id,
            "description": description,
        }

    def _sync_scheduler_task(
        self,
        *,
        task_name: str,
        schedule: str,
        callback_id: str,
        description: str,
        enabled: bool,
        create_if_missing: bool,
    ) -> None:
        task_id = f"{task_name}_{self.group.group_id}"
        payload = self._build_task_state(
            task_id=task_id,
            schedule=schedule,
            callback_id=callback_id,
            description=description,
            enabled=enabled,
        )
        self.put_state_entry(self._TASK_STATE_SCOPE, self._task_state_key(task_name), payload)

        existing_task = get_runtime_task(task_id)
        if existing_task or create_if_missing or enabled:
            upsert_runtime_task(
                task_id=task_id,
                task_type="daily",
                schedule=schedule,
                callback_id=callback_id,
                enabled=enabled,
                group_id=self.group.group_id,
                description=description,
            )

    @service_action(cmd="文件服务")
    async def file_system(self):
        try:
            file_system_flow = {
                "title": "欢迎来到文件服务系统",
                "text": (
                    "请选择以下操作：\n"
                    "1. 整理文件\n"
                    "2. 删除重名文件\n"
                    "3. 修改文件服务背景\n"
                    "4. 设置\n\n"
                    "输入【序号】或【指令】"
                ),
                "image": self.background,
                "routes": {
                    "1": self.organize_files,
                    "2": self.arrange_files,
                    "3": self.change_background,
                    "4": {
                        "title": "文件服务 · 设置",
                        "text": (
                            "请选择设置项：\n"
                            "1. 整理文件设置\n"
                            "2. 自动文件整理设置\n"
                            "3. 个性化设置\n\n"
                            "输入【序号】或【指令】"
                        ),
                        "image": self.background,
                        "routes": {
                            "1": lambda: self.file_sort_settings(),
                            "2": lambda: self.auto_file_sort_settings(),
                            "3": lambda: self.personalization_settings(),
                        },
                    },
                },
            }
            await run_flow(self.group, file_system_flow)
        except Exception as e:
            print(e)
            await self.group.send_msg("❌ 操作超时或出错")

    async def file_sort_settings(self):
        await self.group.send_msg("⚙️【整理文件设置】功能尚未实现")

    async def auto_file_sort_settings(self):
        organize_callback_id = f"file_organize_{self.group.group_id}"
        arrange_callback_id = f"file_arrange_{self.group.group_id}"

        async def organize_callback():
            await self.organize_files()

        async def arrange_callback():
            await self.arrange_files()

        register_runtime_callback(organize_callback_id, organize_callback)
        register_runtime_callback(arrange_callback_id, arrange_callback)

        while True:
            organize_status = "✅ 已开启" if self.auto_organize_enabled else "❌ 已关闭"
            arrange_status = "✅ 已开启" if self.auto_arrange_enabled else "❌ 已关闭"

            msg = (
                "⚙️【自动文件整理设置】\n\n"
                f"1. 自动整理文件 {organize_status}\n"
                f"   当前时间: {self.auto_organize_time}\n\n"
                f"2. 自动删除重名文件 {arrange_status}\n"
                f"   当前时间: {self.auto_arrange_time}\n\n"
                "请输入序号进行设置，或输入【退出】返回"
            )
            await self.group.send_msg(msg)

            try:
                response = await wait_for(30)
                if not response:
                    await self.group.send_msg("⏰ 操作超时，已退出设置")
                    return
                response = response.strip()

                if response == "退出":
                    await self.group.send_msg("✅ 已退出设置")
                    return

                if response == "1":
                    await self._configure_auto_organize(
                        organize_callback_id
                    )
                elif response == "2":
                    await self._configure_auto_arrange(
                        arrange_callback_id
                    )
                else:
                    await self.group.send_msg("❌ 无效选择，请重新输入")
            except Exception as e:
                print(e)
                await self.group.send_msg("❌ 操作出错，已退出")
                return

    async def _configure_auto_organize(self, callback_id):
        """配置自动整理文件"""
        current_status = "开启" if self.auto_organize_enabled else "关闭"
        msg = (
            f"📋 自动整理文件设置\n"
            f"当前状态: {current_status}\n"
            f"当前时间: {self.auto_organize_time}\n\n"
            "1. 开启/关闭自动整理\n"
            "2. 设置整理时间\n"
            "输入序号或【返回】"
        )
        await self.group.send_msg(msg)

        response = await wait_for(30)
        if not response or response.strip() == "返回":
            return

        response = response.strip()
        if response == "1":
            new_status = not self.auto_organize_enabled
            self.auto_organize_enabled = new_status

            if new_status:
                self._sync_scheduler_task(
                    task_name="auto_organize",
                    schedule=self.auto_organize_time,
                    callback_id=callback_id,
                    description="自动整理群文件",
                    enabled=True,
                    create_if_missing=True,
                )
                await self.group.send_msg(
                    f"✅ 自动整理文件已开启\n"
                    f"⏰ 每天 {self.auto_organize_time} 自动执行"
                )
            else:
                self._sync_scheduler_task(
                    task_name="auto_organize",
                    schedule=self.auto_organize_time,
                    callback_id=callback_id,
                    description="自动整理群文件",
                    enabled=False,
                    create_if_missing=False,
                )
                await self.group.send_msg("✅ 自动整理文件已关闭")

        elif response == "2":
            await self.group.send_msg("请输入整理时间（格式: HH:MM，如 04:00）:")
            time_response = await wait_for(30)
            if time_response:
                time_str = time_response.strip()
                if re.match(r"^([0-1]?[0-9]|2[0-3]):[0-5][0-9]$", time_str):
                    self.auto_organize_time = time_str
                    self._sync_scheduler_task(
                        task_name="auto_organize",
                        schedule=time_str,
                        callback_id=callback_id,
                        description="自动整理群文件",
                        enabled=bool(self.auto_organize_enabled),
                        create_if_missing=False,
                    )
                    await self.group.send_msg(f"✅ 整理时间已设置为 {time_str}")
                else:
                    await self.group.send_msg("❌ 时间格式错误，请使用 HH:MM 格式")

    async def _configure_auto_arrange(self, callback_id):
        """配置自动删除重名文件"""
        current_status = "开启" if self.auto_arrange_enabled else "关闭"
        msg = (
            f"📋 自动删除重名文件设置\n"
            f"当前状态: {current_status}\n"
            f"当前时间: {self.auto_arrange_time}\n\n"
            "1. 开启/关闭自动删除重名\n"
            "2. 设置执行时间\n"
            "输入序号或【返回】"
        )
        await self.group.send_msg(msg)

        response = await wait_for(30)
        if not response or response.strip() == "返回":
            return

        response = response.strip()
        if response == "1":
            new_status = not self.auto_arrange_enabled
            self.auto_arrange_enabled = new_status

            if new_status:
                self._sync_scheduler_task(
                    task_name="auto_arrange",
                    schedule=self.auto_arrange_time,
                    callback_id=callback_id,
                    description="自动删除重名文件",
                    enabled=True,
                    create_if_missing=True,
                )
                await self.group.send_msg(
                    f"✅ 自动删除重名文件已开启\n"
                    f"⏰ 每天 {self.auto_arrange_time} 自动执行"
                )
            else:
                self._sync_scheduler_task(
                    task_name="auto_arrange",
                    schedule=self.auto_arrange_time,
                    callback_id=callback_id,
                    description="自动删除重名文件",
                    enabled=False,
                    create_if_missing=False,
                )
                await self.group.send_msg("✅ 自动删除重名文件已关闭")

        elif response == "2":
            await self.group.send_msg("请输入执行时间（格式: HH:MM，如 05:00）:")
            time_response = await wait_for(30)
            if time_response:
                time_str = time_response.strip()
                if re.match(r"^([0-1]?[0-9]|2[0-3]):[0-5][0-9]$", time_str):
                    self.auto_arrange_time = time_str
                    self._sync_scheduler_task(
                        task_name="auto_arrange",
                        schedule=time_str,
                        callback_id=callback_id,
                        description="自动删除重名文件",
                        enabled=bool(self.auto_arrange_enabled),
                        create_if_missing=False,
                    )
                    await self.group.send_msg(f"✅ 执行时间已设置为 {time_str}")
                else:
                    await self.group.send_msg("❌ 时间格式错误，请使用 HH:MM 格式")

    async def personalization_settings(self):
        await self.group.send_msg("⚙️【个性化设置】功能尚未实现")

    @service_action(
        cmd="整理文件",
        desc="整理群文件，将未分类的文件归档到对应文件夹",
        tool_callable=True,
    )
    async def organize_files(self):
        if not self.enabled:
            await self.group.send_msg("❌ 文件服务未开启！")
            return
        try:
            await self.group.send_msg("📋 开始整理群文件...")
            for file in await self.group.get_files():
                await self._process_file(file)
            await self.group.send_msg("✅ 群文件整理完毕")
        except Exception as e:
            print(e)

    @service_action(
        cmd="删除重名文件",
        desc="删除群文件中的重复文件",
        tool_callable=True,
    )
    async def arrange_files(self):
        if not self.enabled:
            await self.group.send_msg("❌ 文件服务未开启！")
            return
        try:
            await self.group.send_msg("📋 开始删除“群友作品”文件夹中的重复作品...")
            folder = await self.group.get_folder("群友作品")
            files = await self.group.get_works(folder=folder)
            seen_files = set()
            for file in files:
                if not (file_name := file.get("file_name")):
                    continue
                if file_name in seen_files:
                    await self.group.delete_file(file)
                else:
                    seen_files.add(file_name)
            await self.group.send_msg("✅ 整理完毕！")
        except Exception as e:
            print(e)

    @service_action(cmd="修改文件服务背景")
    async def change_background(self):
        await self.group.send_msg("📥 请发送新的背景图片（上传图片）或输入【退出】取消：")
        try:
            event = await wait_for_event(60)
            message = event.message
            if not message:
                await self.group.send_msg("❌ 已取消")
                return
            pprint(message)
            image = None
            file_ext = None
            for seg in message:
                if seg.type == "image":
                    image = seg.data["url"]
                    filename = seg.data["file"]
                    if filename.endswith(".jpg"):
                        file_ext = ".jpg"
                    elif filename.endswith(".png"):
                        file_ext = ".png"
                    elif filename.endswith(".gif"):
                        file_ext = ".gif"
                    break
            if not image:
                await self.group.send_msg("❌ 未检测到图片，请重新操作")
                return
            if not file_ext:
                await self.group.send_msg("❌ 图片格式不合法")
                return
            file_name = f"{uuid.uuid4()}{file_ext}"
            save_path = self.group.custom_path / file_name
            save_path = save_path.resolve()
            await download_image(image, str(save_path))
            self.background = str(save_path)
            await self.group.send_msg("✅ 文件服务背景修改成功！")
        except Exception as e:
            print(e)
            await self.group.send_msg("❌ 背景修改失败")

    async def check_illegal_file(self):
        if not (files := await self.group.get_files()):
            return
        uploaded_file = files[0]
        file_name = uploaded_file["file_name"]
        if is_illegal(file_name):
            await self.group.delete_file(uploaded_file)
            await self.group.send_msg("❌ 检测到您发送的文件存在版权问题，已自动撤回。")

    async def _process_file(self, file: File):
        if file["file_name"].startswith("和弦进行"):
            await self.group.delete_file(file)
            return
        match = re.search(r"\.[^.]*$", file["file_name"])
        ext = match.group(0).lower() if match else ""
        folder_map = {
            (".mp3", ".wav", ".ogg", ".flag", ".mp4"): "群友作品",
            (".pdf", ".doc", ".docx", ".txt"): "学习资料",
            (".exe", ".zip", ".7z", ".rar"): "神秘物件",
        }
        for exts, folder_name in folder_map.items():
            if ext in exts:
                target = await self.group.get_folder(folder_name)
                await self.group.move_file(file["file_id"], "/", target["folder"])
                return
        await self.group.delete_file(file)


def is_illegal(file_name) -> bool:
    pattern = r"(?i).*FL.*\.(exe|rar|zip)$"
    return bool(re.match(pattern, file_name))


async def download_image(image_data: str, save_path: str):
    async with aiohttp.ClientSession() as session:
        async with session.get(image_data) as resp:
            if resp.status == 200:
                content = await resp.read()
                os.makedirs(os.path.dirname(save_path), exist_ok=True)
                with open(save_path, "wb") as f:
                    f.write(content)
            else:
                raise Exception(f"下载图片失败，状态码 {resp.status}")


__all__ = ["FileService", "download_image", "is_illegal"]
