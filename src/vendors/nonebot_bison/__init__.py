"""
vendored `nonebot_bison`

此包仅保留无副作用的包元信息。
真正的依赖声明、运行时初始化与模块导入统一由
`src.services.bison.activate_owned_vendor` 代管。
"""

from nonebot.plugin import PluginMetadata


__help__version__ = "0.8.2"
__help__plugin__name__ = "nonebot_bison"
__usage__ = (
    "Bison vendored 运行时已收归 `src.services.bison.activate_owned_vendor` 代管；"
    "请通过 services 层完成加载与接入。"
)

__plugin_meta__ = PluginMetadata(
    name="Bison",
    description="通用订阅推送插件（由 services 层代管）",
    usage=__usage__,
    type="application",
    homepage="https://github.com/felinae98/nonebot-bison",
    config=None,
    supported_adapters=None,
    extra={"version": __help__version__, "docs": "https://nonebot-bison.netlify.app/"},
)

__all__ = [
    "__help__plugin__name__",
    "__help__version__",
    "__plugin_meta__",
    "__usage__",
]
