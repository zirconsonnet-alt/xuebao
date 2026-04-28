"""
vendored `nonebot_plugin_resolver`

根包仅保留无副作用元信息。
真正的 matcher 注册与运行时激活统一由
`src.services.resolver.activate_owned_vendor` 代管。
"""

from nonebot.plugin import PluginMetadata


__usage__ = (
    "Resolver vendored 运行时已收归 `src.services.resolver.activate_owned_vendor` 代管；"
    "请通过 services 层完成加载与接入。"
)

__plugin_meta__ = PluginMetadata(
    name="链接分享解析器",
    description="链接分享解析插件（由 services 层代管）",
    usage=__usage__,
    type="application",
    homepage="https://github.com/zhiyu1998/nonebot-plugin-resolver",
    config=None,
    supported_adapters=None,
    extra={"managed_by": "src.services.resolver"},
)

__all__ = [
    "__plugin_meta__",
    "__usage__",
]
