import os
from io import BytesIO
from pathlib import Path
from typing import Any

from nonebot.adapters.onebot.v11 import MessageSegment

from .renderer import HtmlRenderer


class HtmlCardMaker:
    def __init__(self, config: dict):
        self.config = dict(config or {})
        self.title = self._pick("title", "标题", default="")
        self.subtitle = self._pick("subtitle", "副标题", default="")
        self.text = self._pick("text", "文字", default="")
        self.footer = self._pick("footer", "底部", "hint", "提示", default="")
        self.template_name = str(self._pick("template", "模板", default="default") or "default").strip() or "default"
        self.image_path = self._pick("image", "图片", default="")
        if not self.image_path and self.template_name == "default":
            self.image_path = "background.jpg"
        self.data_dir = "data/nonebot_plugin_cardmaker"
        self.legacy_data_dir = "data/nonebot_plugin_html_card"
        self.font_path = self._resolve_data_path("CFDS.ttf")
        self.background = self._resolve_data_path(self.image_path) if self.image_path else ""
        self.badges = self._coerce_list(self._pick("badges", "标签", default=[]))
        self.stats = self._coerce_list(self._pick("stats", "统计", default=[]))
        self.sections = self._coerce_list(self._pick("sections", "分组", default=[]))
        self.items = self._coerce_list(self._pick("items", "项目", default=[]))
        if self.items and not self.sections:
            self.sections = [{"items": self.items}]

        template_path = self._resolve_template_path(self.template_name)
        self.renderer = HtmlRenderer(template_path=str(template_path))
        os.makedirs(self.data_dir, exist_ok=True)

    def _pick(self, *keys: str, default: Any = "") -> Any:
        for key in keys:
            if key in self.config and self.config.get(key) not in (None, ""):
                return self.config.get(key)
        return default

    @staticmethod
    def _coerce_list(value: Any) -> list[Any]:
        if isinstance(value, list):
            return value
        if isinstance(value, tuple):
            return list(value)
        if value in (None, ""):
            return []
        return [value]

    def _resolve_data_path(self, filename: str) -> str:
        if os.path.isabs(filename):
            return filename
        primary = os.path.join(self.data_dir, filename)
        if os.path.exists(primary):
            return primary
        legacy = os.path.join(self.legacy_data_dir, filename)
        return legacy if os.path.exists(legacy) else primary

    def _resolve_template_path(self, template_name: str) -> Path:
        normalized = str(template_name or "default").strip()
        if not normalized.endswith(".html"):
            normalized = f"{normalized}.html"

        if os.path.isabs(normalized):
            return Path(normalized)

        data_template_path = Path(self.data_dir) / "templates" / normalized
        if data_template_path.exists():
            return data_template_path
        return Path(__file__).parent / "templates" / normalized

    async def create_card(self) -> MessageSegment:
        png = await self.renderer.render(
            title=self.title,
            subtitle=self.subtitle,
            text=self.text,
            footer=self.footer,
            background=self.background,
            font_path=self.font_path,
            badges=self.badges,
            stats=self.stats,
            sections=self.sections,
            items=self.items,
            template_name=self.template_name,
            card_width=int(self._pick("card_width", "宽度", default=860 if self.template_name == "service_menu" else 520)),
            card_min_height=int(self._pick("card_min_height", "最小高度", default=420 if self.template_name == "service_menu" else 360)),
        )
        return MessageSegment.image(BytesIO(png))
