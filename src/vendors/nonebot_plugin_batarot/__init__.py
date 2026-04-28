"""
vendored `nonebot_plugin_batarot`

此包仅保留无副作用的包元信息。
塔罗功能的接入与命令注册统一由 `src.services.tarot` 负责。
"""

from nonebot.plugin import PluginMetadata


__version__ = "0.2.3.post1"

__plugin_meta__ = PluginMetadata(
    name="碧蓝档案塔罗牌",
    description="碧蓝档案塔罗牌，运势预测与魔法占卜",
    usage="使用命令：塔罗牌、今日运势、塔罗牌解读、塔罗占卜",
    homepage="https://github.com/Perseus037/nonebot_plugin_batarot",
    type="application",
    config=None,
    supported_adapters=None,
)

__all__ = ["__plugin_meta__", "__version__"]
