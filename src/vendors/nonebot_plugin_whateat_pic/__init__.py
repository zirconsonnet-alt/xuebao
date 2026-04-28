"""
vendored `nonebot_plugin_whateat_pic`

此包仅保留无副作用的包元信息。
“今天吃什么 / 喝什么” 功能统一由 `src.services.whateat` 负责接管。
"""

from nonebot.plugin import PluginMetadata


__plugin_meta__ = PluginMetadata(
    name="今天吃什么（图片版）",
    description="随机发送吃的或者喝的图片",
    usage="请通过 services 层使用：今天吃什么、今天喝什么、查看菜单、添加菜单、删除菜单。",
    type="application",
    homepage="https://github.com/Cvandia/nonebot-plugin-whateat-pic",
    config=None,
    supported_adapters=None,
)

__all__ = ["__plugin_meta__"]
