"""群聊 AI 助手运行时入口。"""

from .group_reply import GroupReplyMixin


class GroupAIAssistantRuntimeMixin(GroupReplyMixin):
    pass


__all__ = ["GroupAIAssistantRuntimeMixin"]
