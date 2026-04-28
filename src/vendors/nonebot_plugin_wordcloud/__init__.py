"""
vendored `nonebot_plugin_wordcloud`

此包仅保留无副作用的包元信息。
词云命令、定时发送与形状管理统一由 `src.services.wordcloud` 负责。
"""

from nonebot.plugin import PluginMetadata


__plugin_meta__ = PluginMetadata(
    name="词云",
    description="利用群消息生成词云",
    usage="请通过 services 层使用：今日词云、历史词云、设置词云形状、开启词云每日定时发送等命令。",
    homepage="https://github.com/he0119/nonebot-plugin-wordcloud",
    type="application",
    config=None,
    supported_adapters=None,
    extra={"managed_by": "src.services.wordcloud"},
)

__all__ = ["__plugin_meta__"]
