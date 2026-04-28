import re
import traceback
from pprint import pprint
from typing import Dict, Optional, List, Tuple
from datetime import datetime, timedelta
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message, MessageSegment
from src.services.base import BaseService, config_property, service_action
from src.support.core import Services
from src.support.db import (
    add_activity,
    add_activity_application,
    add_activity_participant,
    remove_activity_participant,
    update_activity_application_field,
    update_activity_field,
)
from src.support.group import GroupContext, get_name_by_id, wait_for, run_flow
from src.vendorlibs.cardmaker import CardMaker


class Activity:
    def __init__(self, group: GroupContext, activity_id: int):
        self.db = group.db
        self.group: GroupContext = group
        self.activity_id: int = activity_id

    async def init(self):
        notice_content = (
            f"🎉 新活动上线！\n"
            f"{await self.to_text()}"
        )
        await self.group.send_notice(notice_content)
        success_msg = (
            f"✅ 活动审批成功！\n"
            f"请各位群友通过指令：\n/我要参加{self.activity_id}\n踊跃参与🎉"
        )
        await self.get_folder()
        await self.group.send_msg(success_msg)
 
    @property
    def _data(self) -> Optional[Dict]:
        if not hasattr(self, '_cached_data'):
            data = self.db.get_activity_by_activity_id(self.activity_id)
            self._cached_data = data if data else {}
        return self._cached_data

    @property
    def is_active(self) -> bool:
        now = datetime.now()
        return self.status_code == "active" and self.start_time <= now <= self.end_time

    @property
    def participants(self) -> List[int]:
        return self.db.get_participants_by_activity_id(self.activity_id)

    def add_participant(self, user_id: int) -> Tuple[bool, str]:
        if user_id in self.participants:
            return False, '您已在活动中'
        return add_activity_participant(
            self.db,
            user_id=user_id,
            activity_id=self.activity_id,
        )

    def remove_participant(self, user_id: int) -> bool:
        if user_id not in self.participants:
            return False
        if remove_activity_participant(
            self.group.db,
            user_id=user_id,
            activity_id=self.activity_id,
        ):
            return True
        return False

    @property
    def start_time(self) -> Optional[datetime]:
        if not self._data.get('start_time'):
            return None
        return datetime.fromisoformat(self._data['start_time'])

    @start_time.setter
    def start_time(self, value: datetime):
        if not self._data:
            raise ValueError("Activity data not available")
        iso_str = value.isoformat()
        self._data['start_time'] = iso_str
        update_activity_field(self.db, self.activity_id, 'start_time', iso_str)

    @property
    def end_time(self) -> Optional[datetime]:
        if not self._data.get('end_time'):
            return None
        return datetime.fromisoformat(self._data['end_time'])

    @end_time.setter
    def end_time(self, value: datetime):
        if not self._data:
            raise ValueError("Activity data not available")
        iso_str = value.isoformat()
        self._data['end_time'] = iso_str
        update_activity_field(self.db, self.activity_id, 'end_time', iso_str)

    @property
    def activity_name(self) -> str:
        return self._data.get('activity_name', '')

    @activity_name.setter
    def activity_name(self, value: str):
        if not self._data:
            raise ValueError("Activity data not available")
        self._data['activity_name'] = value
        update_activity_field(self.db, self.activity_id, 'activity_name', value)

    @property
    def requirement(self) -> str:
        return self._data.get('requirement', '')

    @requirement.setter
    def requirement(self, value: str):
        if not self._data:
            raise ValueError("Activity data not available")
        self._data['requirement'] = value
        update_activity_field(self.db, self.activity_id, 'requirement', value)

    @property
    def content(self) -> str:
        return self._data.get('content', '')

    @content.setter
    def content(self, value: str):
        if not self._data:
            raise ValueError("Activity data not available")
        self._data['content'] = value
        update_activity_field(self.db, self.activity_id, 'content', value)

    @property
    def reward(self) -> str:
        return self._data.get('reward', '')

    @reward.setter
    def reward(self, value: str):
        if not self._data:
            raise ValueError("Activity data not available")
        self._data['reward'] = value
        update_activity_field(self.db, self.activity_id, 'reward', value)

    @property
    def creator_id(self) -> Optional[int]:
        return self._data.get('creator_id')

    @creator_id.setter
    def creator_id(self, value: int):
        if not self._data:
            raise ValueError("Activity data not available")
        self.db.add_member(value)
        self._data['creator_id'] = value
        update_activity_field(self.db, self.activity_id, 'creator_id', value)

    @property
    def status_code(self) -> str:
        return (self._data or {}).get("status") or "active"

    @status_code.setter
    def status_code(self, value: str):
        if not self._data:
            raise ValueError("Activity data not available")
        self._data["status"] = value
        update_activity_field(self.db, self.activity_id, "status", value)

    @property
    def status(self) -> str:
        now = datetime.now()
        if not self.start_time or not self.end_time:
            return "数据异常"
        if self.status_code == "draft":
            return "草稿"
        if self.status_code == "cancelled":
            return "已取消"
        if self.status_code == "ended":
            return "已结束"
        if now < self.start_time:
            return "未开始"
        elif now > self.end_time:
            return "已结束"
        return "进行中"

    async def to_text(self) -> str:
        msg = (
            f"📌 活动ID：{self.activity_id}\n"
            f"🎪 名称：{self.activity_name}\n"
            f"💪 要求：{self.requirement}\n"
            f"📜 内容：{self.content}\n"
            f"🏆 奖励：{self.reward}\n"
            f"🕒 时间：\n"
            f"{self.start_time.strftime('%Y-%m-%d %H:%M')} ~\n"
            f"{self.end_time.strftime('%Y-%m-%d %H:%M')}\n"
            f"⏳ 状态：{self.status}\n"
            f"👤 发起人：{await get_name_by_id(self.group.group_id, self.creator_id)}\n"
        )
        if self.participants:
            msg += f"👥 参与者({len(self.participants)}人)：\n"
            participant_list = []
            for i, uid in enumerate(self.participants):
                name = await get_name_by_id(self.group.group_id, uid)
                participant_list.append(f"{i + 1}：{name}")
            msg += '，\n'.join(participant_list)
        return msg

    async def at_all(self):
        await self.group.send_msg(Message(MessageSegment.at(uid) for uid in self.participants))

    async def get_folder(self) -> str:
        return await self.group.get_folder(f'{self.activity_id}号活动-{self.activity_name}')

    async def submit(self, event: GroupMessageEvent):
        folder = await self.get_folder()
        file = await self.group.get_resent_file(event.user_id)
        if not file:
            await self.group.send_msg("⛔ 未检测到您发送的文件！")
        file_path = await self.group.download_file(file)
        print(file_path)
        print(file['file_name'])
        print(folder)
        await self.group.upload_file(file_path, file['file_name'], folder)
        await self.group.send_msg(f"✅ 已将{file['file_name']}上传至活动文件夹中！")

    async def quit(self, event: GroupMessageEvent):
        uid = event.user_id
        if uid not in self.participants:
            await self.group.send_msg(MessageSegment.at(uid) + "⛔ 您未参与该活动")
            return
        if uid == self.creator_id:
            await self.end(event)
            return
        self.remove_participant(uid)
        await self.group.send_msg(
            MessageSegment.at(uid) +
            f"✅ 已成功退出活动【{self.activity_name}】\n"
            f"当前参与人数：{len(self.participants)}人"
        )

    async def end(self, event: GroupMessageEvent):
        uid = event.user_id
        if uid != self.creator_id:
            await self.group.send_msg(MessageSegment.at(uid) + " ⛔ 只有发起者可结束活动")
            return
        self.end_time = datetime.now()
        self.status_code = "ended"
        notice = (
            f"🎺 活动提前结束通知\n"
            f"🎪 活动名称：{self.activity_name}\n"
            f"🕒 结束时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
            f"⏳ 状态：已结束\n"
            f"感谢{len(self.participants)}位参与者的支持！"
        )
        await self.at_all()
        await self.group.send_msg(notice)


class Application:
    def __init__(self, group: GroupContext, application_id: int):
        self.db = group.db
        self.group = group
        self.application_id = application_id

    @property
    def _data(self) -> Optional[Dict]:
        if not hasattr(self, '_cached_data'):
            data = self.db.get_application(self.application_id)
            if not data:
                return None
            self._cached_data = data
        return self._cached_data

    @property
    def creator_id(self) -> Optional[int]:
        return self._data['creator_id'] if self._data else None

    @creator_id.setter
    def creator_id(self, value: int):
        if not self._data:
            raise ValueError("Application data not available")
        self.db.add_member(value)
        self._data['creator_id'] = value
        update_activity_application_field(self.db, self.application_id, 'creator_id', value)

    @property
    def activity_name(self) -> str:
        return self._data['activity_name'] if self._data else ""

    @activity_name.setter
    def activity_name(self, value: str):
        if not self._data:
            raise ValueError("Application data not available")
        self._data['activity_name'] = value
        update_activity_application_field(self.db, self.application_id, 'activity_name', value)

    @property
    def requirement(self) -> str:
        return self._data['requirement'] if self._data else ""

    @requirement.setter
    def requirement(self, value: str):
        if not self._data:
            raise ValueError("Application data not available")
        self._data['requirement'] = value
        update_activity_application_field(self.db, self.application_id, 'requirement', value)

    @property
    def content(self) -> str:
        return self._data['content'] if self._data else ""

    @content.setter
    def content(self, value: str):
        if not self._data:
            raise ValueError("Application data not available")
        self._data['content'] = value
        update_activity_application_field(self.db, self.application_id, 'content', value)

    @property
    def reward(self) -> str:
        return self._data['reward'] if self._data else ""

    @reward.setter
    def reward(self, value: str):
        if not self._data:
            raise ValueError("Application data not available")
        self._data['reward'] = value
        update_activity_application_field(self.db, self.application_id, 'reward', value)

    @property
    def duration(self) -> int:
        return self._data['duration'] if self._data else 0

    @duration.setter
    def duration(self, value: int):
        if not self._data:
            raise ValueError("Application data not available")
        self._data['duration'] = value
        update_activity_application_field(self.db, self.application_id, 'duration', value)

    @property
    def create_time(self) -> Optional[datetime]:
        if not self._data or not self._data.get('create_time'):
            return None
        return datetime.fromisoformat(self._data['create_time'])

    @create_time.setter
    def create_time(self, value: datetime):
        if not self._data:
            raise ValueError("Application data not available")
        iso_str = value.isoformat()
        self._data['create_time'] = iso_str
        update_activity_application_field(self.db, self.application_id, 'create_time', iso_str)

    @property
    def status(self) -> int:
        return self._data['status'] if self._data else -1

    @status.setter
    def status(self, value: int):
        if not self._data:
            raise ValueError("Application data not available")
        self._data['status'] = value
        update_activity_application_field(self.db, self.application_id, 'status', value)

    async def approve(self) -> Optional[Activity]:
        if self.status != 0:
            await self.group.send_msg("⛔ 该申请已被处理")
            return
        application = self.db.get_application(self.application_id)
        if not application:
            return None
        duration = timedelta(seconds=application['duration'])
        end_time = datetime.now() + duration
        activity_id = add_activity(
            self.db,
            creator_id=application['creator_id'],
            activity_name=application['activity_name'],
            requirement=application['requirement'],
            content=application['content'],
            reward=application['reward'],
            start=datetime.now(),
            end=end_time,
            status="active",
            source_application_id=self.application_id,
        )
        self.status = 1
        activity = Activity(self.group, activity_id)
        await activity.init()
        return activity


class ActivityService(BaseService):
    service_type = Services.Activity
    enable_requires_bot_admin = True
    default_config = {
        "enabled": False,
        "background": None
    }
    enabled = config_property("enabled")
    background = config_property("background")

    def __init__(self, group: GroupContext):
        super().__init__(group)
        self.applications = self._load_applications()
        self.activities = self._load_activities()
        pprint(self.applications)
        pprint(self.activities)

    def _load_applications(self) -> Dict[int, Application]:
        return {app_id: Application(self.group, app_id) for app_id in self.group.db.get_all_applications(status=0)}

    def _load_activities(self) -> Dict[int, Activity]:
        return {act_id: Activity(self.group, act_id) for act_id in self.group.db.get_all_activities()}

    @staticmethod
    def _parse_duration(input_str: str) -> Optional[timedelta]:
        match = re.compile(r"^(\d+)([dhDHT天小时])$", re.IGNORECASE).match(input_str.strip().lower())
        if not match:
            return None
        value, unit = match.groups()
        value = int(value)
        unit_map = {
            'd': 'days', '天': 'days',
            'h': 'hours', '小时': 'hours'
        }
        try:
            if unit_map.get(unit) == 'days' and 1 <= value <= 30:
                return timedelta(days=value)
            if unit_map.get(unit) == 'hours' and 1 <= value <= 720:
                return timedelta(hours=value)
        except ValueError:
            return None

    @service_action(cmd="创建活动申请", desc="申请创建一个新活动")
    async def create_application(self, event: GroupMessageEvent):
        try:
            steps = [
                ("活动名称", "请输入活动名称（30秒）："),
                ("参与要求", "请输入参与要求（60秒）："),
                ("活动内容", "请输入活动内容（90秒）："),
                ("活动时长", "请输入活动时长（示例：3天/d，3h/小时）："),
                ("活动奖励", "请输入活动奖励（60秒）：")
            ]
            responses = {}
            for field, prompt in steps:
                await self.group.send_msg(MessageSegment.at(event.user_id) + prompt)
                response = await wait_for(60)
                if not response or response.lower() == '退出':
                    await self.group.send_msg("❌ 活动创建已取消")
                    return
                if field == "活动时长":
                    if not (response := self._parse_duration(response)):
                        await self.group.send_msg("⛔ 无效的时长格式")
                        return
                responses[field] = response
            application_id = add_activity_application(self.group.db, {
                'creator_id': event.user_id,
                'activity_name': responses["活动名称"],
                'requirement': responses["参与要求"],
                'content': responses["活动内容"],
                'reward': responses["活动奖励"],
                'duration': responses['活动时长'].total_seconds()
            })
            self.applications[application_id] = Application(self.group, application_id)
            await self.group.send_msg(f"✅ 活动申请已提交！申请ID：{application_id}\n请通知管理员审核！")
        except Exception as e:
            print(e)
            print(f"活动创建失败: {traceback.format_exc()}")
            await self.group.send_msg("⚠️ 活动创建失败，请联系管理员处理")

    @service_action(cmd="审批活动", need_arg=True, desc="审批活动申请")
    async def handle_approval(self, arg: Message):
        try:
            raw = arg.extract_plain_text().strip()
            match = re.search(r"\d+", raw)
            if not match:
                await self.group.send_msg("⛔ 您的输入不合法")
                return
            application_id = int(match.group())
            if not (application := self.applications.get(application_id)):
                await self.group.send_msg(f"⛔ id为{application_id}的申请不存在")
                return
            if activity := await application.approve():
                self.activities[activity.activity_id] = activity
                del self.applications[application_id]
                return
        except ValueError:
            await self.group.send_msg(f"⛔ 您的输入不合法")
            return
        except Exception as e:
            print(e)
            await self.group.send_msg(f"⚠️ 审批失败，请联系训豹师处理bug。")
            return

    @service_action(cmd="我要参加", need_arg=True, desc="参加指定活动")
    async def join_activity(self, event: GroupMessageEvent, arg: Message):
        try:
            raw = arg.extract_plain_text().strip()
            match = re.search(r"\d+", raw)
            if not match:
                await self.group.send_msg(f"⛔ 不存在这个活动号{raw}")
                return
            activity_id = int(match.group())
            if not (activity := self.activities.get(activity_id)):
                await self.group.send_msg("⛔ 指定活动不存在")
                return
            if not activity.is_active:
                await self.group.send_msg(f"⛔ 活动当前状态：{activity.status}")
                return
            resp = activity.add_participant(event.user_id)
            if not resp[0]:
                await self.group.send_msg(resp[1])
                return
            msg = (
                MessageSegment.at(event.user_id) +
                f"\n✅ 成功参与活动【{activity.activity_name}】\n" +
                MessageSegment.at(activity.creator_id) +
                f" 当前参与人数：{len(activity.participants)}人"
            )
            await self.group.send_msg(msg)
        except ValueError:
            await self.group.send_msg(f"⛔ 不存在这个活动号{arg.extract_plain_text().strip()}")
            return
        except Exception as e:
            print(e)
            print(f"参与失败: {traceback.format_exc()}")
            await self.group.send_msg("⚠️ 参与活动失败，请稍后重试")

    @service_action(cmd="发起活动", desc="发起一个活动（创建活动申请）")
    async def start_activity(self, event: GroupMessageEvent):
        await self.create_application(event)

    @service_action(cmd="通过活动", need_arg=True, desc="通过活动申请（审批活动）")
    async def approve_activity(self, arg: Message):
        await self.handle_approval(arg)

    @service_action(cmd="报名活动", need_arg=True, desc="报名参加活动")
    async def enroll_activity(self, event: GroupMessageEvent, arg: Message):
        await self.join_activity(event, arg)

    @service_action(cmd="刷新活动", desc="刷新活动列表", visible=False)
    async def refresh_activities(self):
        current_ids = {a.activity_id for a in self.activities.values()}
        latest_ids = set(self.group.db.get_all_activities())
        for expired_id in current_ids - latest_ids:
            del self.activities[expired_id]
        for new_id in latest_ids - current_ids:
            self.activities[new_id] = Activity(self.group, new_id)

    @service_action(cmd="我的活动", desc="查看我参与的活动")
    async def get_activity(self, event: GroupMessageEvent, arg: Message) -> Optional[Activity]:
        aid = self.group.db.get_activities_by_uid(event.user_id)
        if not aid:
            return
        activity = self.activities[aid]
        if not activity:
            await self.group.send_msg("您未参加正在进行的活动。")
            return
        if not (user_input := arg.extract_plain_text().strip()):
            data = {
                '标题': '欢迎使用活动系统！',
                '文字': (
                    '@活动全体成员，请发送1；\n'
                    '上传活动文件，请发送2；\n'
                    '退出活动，请发送3；\n'
                    '解散活动，请发送4.\n'
                    '修改活动，请发送5。'
                ),
                '图片': 'background.png',
            }
            await self.group.send_msg(CardMaker(data).create_card())
            await self.group.send_msg(Message(await activity.to_text()))
            resp = await wait_for(60)
            if not resp or resp not in ['1', '2', '3', '4', '5']:
                await self.group.send_msg("❌ 输入无效，系统已自动退出")
                return
            if resp == '1':
                await activity.at_all()
                return
            elif resp == '2':
                await activity.submit(event)
                return
            elif resp == '3':
                await activity.quit(event)
                return
            elif resp == '4':
                await activity.end(event)
                return
            elif resp == '5':
                if event.user_id != activity.creator_id:
                    await self.group.send_msg(MessageSegment.at(event.user_id) + " ⛔ 只有活动发起者可以修改信息")
                    return
                option_msg = (
                    "请选择要修改的内容：\n"
                    "1. 活动名称\n"
                    "2. 参与要求\n"
                    "3. 活动内容\n"
                    "4. 活动奖励\n"
                    "5. 延长活动时间"
                )
                await self.group.send_msg(option_msg)
                choice = await wait_for(60)
                if not choice or choice not in ['1', '2', '3', '4', '5']:
                    await self.group.send_msg("❌ 输入无效，修改已取消")
                    return
                if choice == '1':
                    await self.group.send_msg("请输入新的活动名称：")
                    new_name = await wait_for(60)
                    if not new_name:
                        return
                    activity.activity_name = new_name
                    await self.group.send_msg("✅ 活动名称已更新！")
                elif choice == '2':
                    await self.group.send_msg("请输入新的参与要求：")
                    new_req = await wait_for(60)
                    if not new_req:
                        return
                    activity.requirement = new_req
                    await self.group.send_msg("✅ 参与要求已更新！")
                elif choice == '3':
                    await self.group.send_msg("请输入新的活动内容：")
                    new_content = await wait_for(60)
                    if not new_content:
                        return
                    activity.content = new_content
                    await self.group.send_msg("✅ 活动内容已更新！")
                elif choice == '4':
                    await self.group.send_msg("请输入新的活动奖励：")
                    new_reward = await wait_for(60)
                    if not new_reward:
                        return
                    activity.reward = new_reward
                    await self.group.send_msg("✅ 活动奖励已更新！")
                elif choice == '5':
                    await self.group.send_msg("请输入要延长的时间（例如1d或12h）：")
                    duration_input = await wait_for(60)
                    if not duration_input:
                        return
                    duration = self._parse_duration(duration_input)
                    if not duration or duration.total_seconds() <= 0:
                        await self.group.send_msg("⛔ 无效时长格式，请使用类似3d或12h的格式")
                        return
                    new_end_time = activity.end_time + duration
                    activity.end_time = new_end_time
                    await self.group.send_msg(
                        f"✅ 活动结束时间已延长至 {new_end_time.strftime('%Y-%m-%d %H:%M')}\n"
                        f"当前状态：{activity.status}"
                    )
        elif user_input == '@全体':
            await activity.at_all()
        elif user_input == '上传':
            await activity.submit(event)
        elif user_input == '退出':
            await activity.quit(event)
        elif user_input == '解散':
            await activity.end(event)
        elif user_input == '修改':
            await activity.end(event)

    @service_action(cmd="活动服务")
    async def activity_service_menu(self):
        if not self.enabled:
            await self.group.send_msg("❌ 活动服务未开启！")
            return
        routes = {
            "1": self.create_application,
            "2": self.handle_approval,
            "3": self.join_activity,
            "4": self.start_activity,
            "5": self.approve_activity,
            "6": self.enroll_activity,
            "7": self.refresh_activities,
            "8": self.get_activity,
        }
        flow = {
            "title": "欢迎使用活动服务",
            "text": (
                "请选择以下操作：\n"
                "1. 创建活动申请\n"
                "2. 审批活动\n"
                "3. 我要参加\n"
                "4. 发起活动\n"
                "5. 通过活动\n"
                "6. 报名活动\n"
                "7. 刷新活动\n"
                "8. 我的活动\n\n"
                "输入【序号】或【指令】"
            ),
            "routes": routes,
        }
        await run_flow(self.group, flow)
