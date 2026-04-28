from datetime import datetime
from typing import Any, Dict

import nonebot

from src.support.core import (
    EmptyInput,
    GetGroupHonorInput,
    GetGroupMemberInfoInput,
    GetGroupMemberListInput,
    GetUserInfoInput,
    Services,
    ai_tool,
)
from src.support.group import GroupContext, run_flow

from .base import BaseService, config_property, service_action

class InfoService(BaseService):
    service_type = Services.Info
    default_config = {"enabled": True}
    enabled = config_property("enabled")

    def __init__(self, group: GroupContext):
        super().__init__(group)

    @ai_tool(name="get_group_info", desc="获取当前群的基本信息，包括群名称、成员数量等", category="query", input_model=EmptyInput)
    async def get_group_info_core(self, user_id: int, group_id: int, **kwargs) -> Dict[str, Any]:
        if not group_id:
            return {"success": False, "message": "无法获取群ID"}
        try:
            info = await nonebot.get_bot().get_group_info(group_id=group_id)
            data = {
                "群号": info.get("group_id"),
                "群名称": info.get("group_name"),
                "成员数": info.get("member_count"),
                "最大成员数": info.get("max_member_count"),
            }
            return {"success": True, "message": "执行成功", "data": data}
        except Exception as exc:
            return {"success": False, "message": str(exc)}

    @ai_tool(
        name="get_group_member_list",
        desc="获取当前群的成员列表",
        parameters={"type": "object", "properties": {"limit": {"type": "integer", "description": "返回的成员数量限制，默认10"}}, "required": []},
        category="query",
        input_model=GetGroupMemberListInput,
    )
    async def get_group_member_list_core(self, user_id: int, group_id: int, **kwargs) -> Dict[str, Any]:
        if not group_id:
            return {"success": False, "message": "无法获取群ID"}
        limit = kwargs.get("limit") or 10
        try:
            members = await nonebot.get_bot().get_group_member_list(group_id=group_id)
            members.sort(key=lambda item: item.get("last_sent_time", 0), reverse=True)
            members = members[:limit]
            result = []
            for member in members:
                result.append(
                    {
                        "昵称": member.get("nickname"),
                        "群名片": member.get("card") or member.get("nickname"),
                        "角色": {"owner": "群主", "admin": "管理员", "member": "成员"}.get(member.get("role"), "成员"),
                        "入群时间": datetime.fromtimestamp(member.get("join_time", 0)).strftime("%Y-%m-%d"),
                        "最后发言": datetime.fromtimestamp(member.get("last_sent_time", 0)).strftime("%Y-%m-%d %H:%M"),
                    }
                )
            return {"success": True, "message": "执行成功", "data": {"成员列表": result, "总人数": len(members)}}
        except Exception as exc:
            return {"success": False, "message": str(exc)}

    @ai_tool(
        name="get_user_info",
        desc="获取指定用户或当前说话用户的详细信息",
        parameters={"type": "object", "properties": {"user_id": {"type": "integer", "description": "用户QQ号，不填则获取当前说话的用户"}}, "required": []},
        category="query",
        input_model=GetUserInfoInput,
    )
    async def get_user_info_core(self, user_id: int, group_id: int, **kwargs) -> Dict[str, Any]:
        if not user_id:
            return {"success": False, "message": "无法获取用户ID"}
        try:
            info = await nonebot.get_bot().get_stranger_info(user_id=user_id)
            data = {
                "QQ号": info.get("user_id"),
                "昵称": info.get("nickname"),
                "性别": {"male": "男", "female": "女", "unknown": "未知"}.get(info.get("sex"), "未知"),
                "年龄": info.get("age"),
            }
            return {"success": True, "message": "执行成功", "data": data}
        except Exception as exc:
            return {"success": False, "message": str(exc)}

    @ai_tool(
        name="get_group_member_info",
        desc="获取指定群成员的详细信息，包括入群时间、最后发言时间、群名片等",
        parameters={"type": "object", "properties": {"user_id": {"type": "integer", "description": "用户QQ号，不填则获取当前说话的用户"}}, "required": []},
        category="query",
        input_model=GetGroupMemberInfoInput,
    )
    async def get_group_member_info_core(self, user_id: int, group_id: int, **kwargs) -> Dict[str, Any]:
        if not group_id or not user_id:
            return {"success": False, "message": "无法获取群ID或用户ID"}
        try:
            info = await nonebot.get_bot().get_group_member_info(group_id=group_id, user_id=user_id)
            data = {
                "QQ号": info.get("user_id"),
                "昵称": info.get("nickname"),
                "群名片": info.get("card") or info.get("nickname"),
                "角色": {"owner": "群主", "admin": "管理员", "member": "成员"}.get(info.get("role"), "成员"),
                "头衔": info.get("title") or "无",
                "入群时间": datetime.fromtimestamp(info.get("join_time", 0)).strftime("%Y-%m-%d %H:%M"),
                "最后发言": datetime.fromtimestamp(info.get("last_sent_time", 0)).strftime("%Y-%m-%d %H:%M"),
                "等级": info.get("level"),
            }
            return {"success": True, "message": "执行成功", "data": data}
        except Exception as exc:
            return {"success": False, "message": str(exc)}

    @ai_tool(
        name="get_group_honor",
        desc="获取群荣誉信息，包括龙王、群聊之火等",
        parameters={"type": "object", "properties": {"type": {"type": "string", "enum": ["talkative", "performer", "legend", "strong_newbie", "emotion", "all"], "description": "荣誉类型"}}, "required": []},
        category="query",
        input_model=GetGroupHonorInput,
    )
    async def get_group_honor_core(self, user_id: int, group_id: int, **kwargs) -> Dict[str, Any]:
        if not group_id:
            return {"success": False, "message": "无法获取群ID"}
        honor_type = kwargs.get("type", "all")
        try:
            info = await nonebot.get_bot().get_group_honor_info(group_id=group_id, type=honor_type)
            result = {"群号": info.get("group_id")}
            if info.get("current_talkative"):
                talkative = info["current_talkative"]
                result["当前龙王"] = {"昵称": talkative.get("nickname"), "连续天数": talkative.get("day_count")}
            if info.get("talkative_list"):
                result["历史龙王"] = [
                    {"昵称": item.get("nickname"), "描述": item.get("description")}
                    for item in info["talkative_list"][:5]
                ]
            return {"success": True, "message": "执行成功", "data": result}
        except Exception as exc:
            return {"success": False, "message": str(exc)}

__all__ = ["InfoService"]
