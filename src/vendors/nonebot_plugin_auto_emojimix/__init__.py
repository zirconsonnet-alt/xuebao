"""
vendored `nonebot_plugin_auto_emojimix`

此包仅保留无副作用的包元信息。
命令接管与触发逻辑统一由 `src.services.emojimix` 负责。
"""

from nonebot.plugin import PluginMetadata


__plugin_meta__ = PluginMetadata(
    name="自动合成emoji",
    description="更好的 emoji 合成，包含自动触发合成与数据支持",
    usage="{emoji1}+{emoji2}，如：😎+😁",
    type="application",
    homepage="https://github.com/Misty02600/nonebot-plugin-auto-emojimix",
    config=None,
    supported_adapters=None,
)

__all__ = ["__plugin_meta__"]
