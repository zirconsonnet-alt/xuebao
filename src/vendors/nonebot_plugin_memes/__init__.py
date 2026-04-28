"""
vendored `nonebot_plugin_memes`

此包仅保留无副作用的包元信息。
表情包功能的命令接入与对外行为统一由 `src.services.meme` 负责。
"""

from nonebot.plugin import PluginMetadata


__plugin_meta__ = PluginMetadata(
    name="表情包制作",
    description="制作各种沙雕表情包",
    usage="请通过 services 层使用：表情包、表情包列表、表情包搜索、表情包详情、随机表情包。",
    type="application",
    homepage="https://github.com/noneplugin/nonebot-plugin-memes",
    config=None,
    supported_adapters=None,
)

__all__ = ["__plugin_meta__"]
