"""
`src.services` 是新的标准业务入口。

当前目录直接承载各个公开 service 模块，
复杂业务域的内部实现下沉到 `_ai`、`_vision` 等内部包或 `src.vendors` 下的 vendored 模块。
"""

import importlib

from src.support.core import Services
from .vendor_registry import iter_vendor_owner_modules, validate_vendor_plugin_ownership


SERVICE_CLASS_IMPORTS: dict[Services, tuple[str, str]] = {
    Services.File: ("src.services.file", "FileService"),
    Services.Request: ("src.services.request", "RequestService"),
    Services.Activity: ("src.services.activity", "ActivityService"),
    Services.Vote: ("src.services.vote", "VoteService"),
    Services.Title: ("src.services.title", "TitleService"),
    Services.Chat: ("src.services.chat", "ChatService"),
    Services.Composition: ("src.services.composition", "CompositionService"),
    Services.Info: ("src.services.info", "InfoService"),
    Services.Schedule: ("src.services.schedule", "ScheduleService"),
    Services.Wordcloud: ("src.services.wordcloud", "WordcloudService"),
    Services.Dialectlist: ("src.services.dialectlist", "DialectlistService"),
    Services.Emojimix: ("src.services.emojimix", "EmojimixService"),
    Services.AI: ("src.services.ai", "AIService"),
    Services.Tarot: ("src.services.tarot", "TarotService"),
    Services.Meme: ("src.services.meme", "MemeService"),
    Services.Vision: ("src.services.vision", "VisionService"),
    Services.SignIn: ("src.services.sign_in", "SignInService"),
    Services.Werewolf: ("src.services.werewolf", "WerewolfService"),
    Services.MathGame: ("src.services.math_game", "MathGameService"),
    Services.TurtleSoup: ("src.services.sp", "TurtleSoupService"),
    Services.Whateat: ("src.services.whateat", "WhateatService"),
    Services.Reminder: ("src.services.reminder", "ReminderService"),
    Services.Bison: ("src.services.bison", "BisonService"),
    Services.Multincm: ("src.services.multincm", "MultiNCMService"),
    Services.Resolver: ("src.services.resolver", "ResolverService"),
    Services.Audio2Midi: ("src.services.audio2midi", "Audio2MidiService"),
    Services.Suno: ("src.services.suno", "SunoService"),
}


def iter_internal_service_modules() -> tuple[str, ...]:
    modules = {module_path for module_path, _ in SERVICE_CLASS_IMPORTS.values()}
    modules.update(iter_vendor_owner_modules())
    return tuple(sorted(modules))


def activate_vendor_owner(module) -> None:
    activate = getattr(module, "activate_owned_vendor", None)
    if callable(activate):
        activate()


def load_internal_services() -> None:
    validate_vendor_plugin_ownership()
    # 显式加载所有服务模块，确保 BaseService 子类已注册。
    for module_name in iter_internal_service_modules():
        try:
            module = importlib.import_module(module_name)
            activate_vendor_owner(module)
        except Exception as exc:
            print(f"[src.services] 跳过模块 {module_name}: {exc}")


__all__ = [
    "activate_vendor_owner",
    "SERVICE_CLASS_IMPORTS",
    "iter_internal_service_modules",
    "load_internal_services",
]
