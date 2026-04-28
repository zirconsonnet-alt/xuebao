from abc import abstractmethod
from typing import Callable, Tuple, List, Union
from nonebot.internal.matcher import Matcher
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message
from .tools import command_maker_tuple, send_image, wait_for
from src.vendorlibs.cardmaker import CardMaker


class CommandHandler:
    def __init__(self, matcher: Matcher, event: GroupMessageEvent, arg: Union[Message, str]):
        self.matcher = matcher
        self.event = event
        self.msg = arg.extract_plain_text().strip() if isinstance(arg, Message) else arg
        self.commands: List[Tuple[str, Callable]] = self.get_commands()
        self.command_map = {}
        self._init_command_map()

    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @property
    @abstractmethod
    def background(self) -> str:
        pass

    @abstractmethod
    def get_commands(self) -> List[Tuple[str, Callable]]:
        pass

    def _init_command_map(self):
        for idx, (cmd, handler) in enumerate(self.commands, start=1):
            self.command_map[str(idx)] = handler
            self.command_map[cmd] = handler

    async def execute(self):
        if not self.msg:
            await self._show_welcome_card()
            self.msg = await wait_for(30)
        if self.msg in self.command_map:
            await self.command_map[self.msg]()
        else:
            await self.matcher.finish("无效指令，请输入序号或有效指令")

    async def _show_welcome_card(self):
        command_text = "\n".join(
            f"{idx}. {cmd}" for idx, (cmd, _) in enumerate(self.commands, start=1)
        )
        card_data = {
            '标题': f'欢迎来到{self.name}系统',
            '文字': (
                '请选择以下操作：\n'
                f'{command_text}\n\n'
                '输入【序号】或【指令】开始游戏'
            ),
            '图片': self.background
        }
        await self.matcher.send(CardMaker(card_data).create_card())


__all__ = ["CommandHandler"]
