"""
vendored `nonebot_plugin_multincm`

根包仅保留无副作用元信息。
依赖声明、命令加载、缓存清理与登录启动任务统一由
`src.services.multincm.activate_owned_vendor` 代管。
"""

from nonebot.plugin import PluginMetadata


__version__ = "1.3.1.post1"
__usage__ = (
    "MultiNCM vendored 运行时已收归 `src.services.multincm.activate_owned_vendor` 代管；"
    "请通过 services 层完成加载与接入。"
)

__plugin_meta__ = PluginMetadata(
    name="MultiNCM",
    description="网易云多选点歌（由 services 层代管）",
    usage=__usage__,
    homepage="https://github.com/lgc-NB2Dev/nonebot-plugin-multincm",
    type="application",
    config=None,
    supported_adapters=None,
    extra={"License": "MIT", "Author": "LgCookie", "managed_by": "src.services.multincm"},
)

__all__ = [
    "__plugin_meta__",
    "__usage__",
    "__version__",
]
