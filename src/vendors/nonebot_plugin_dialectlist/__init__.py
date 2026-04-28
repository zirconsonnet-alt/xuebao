"""
vendored `nonebot_plugin_dialectlist`

此包仅保留无副作用的包元信息。
B 话榜的命令注册与对外行为统一由 `src.services.dialectlist` 负责。
"""

from nonebot.plugin import PluginMetadata


__plugin_meta__ = PluginMetadata(
    name="B话排行榜",
    description="调查群成员消息数量并生成 B 话榜",
    usage="请通过 services 层使用：B话榜、看看B话、今日B话榜等命令。",
    homepage="https://github.com/ChenXu233/nonebot_plugin_dialectlist",
    type="application",
    config=None,
    supported_adapters=None,
)

__all__ = ["__plugin_meta__"]
