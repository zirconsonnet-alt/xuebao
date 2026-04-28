import base64
import mimetypes
from pathlib import Path

from playwright.async_api import async_playwright
from jinja2 import Template


class HtmlRenderer:
    def __init__(self, template_path: str):
        self.template_path = template_path

    @staticmethod
    def _build_data_uri(path: str | None) -> str:
        raw_path = str(path or "").strip()
        if not raw_path:
            return ""

        file_path = Path(raw_path)
        if not file_path.exists() or not file_path.is_file():
            return ""

        mime_type, _ = mimetypes.guess_type(str(file_path))
        mime_type = mime_type or "application/octet-stream"
        return f"data:{mime_type};base64,{base64.b64encode(file_path.read_bytes()).decode()}"

    async def render(self, **kwargs) -> bytes:
        with open(self.template_path, "r", encoding="utf-8") as f:
            template = Template(f.read())

        card_width = int(kwargs.get("card_width", 520))
        text = kwargs.get("text", "")
        html = template.render(
            title=kwargs.get("title"),
            subtitle=kwargs.get("subtitle", ""),
            text=text,
            footer=kwargs.get("footer"),
            background=self._build_data_uri(kwargs.get("background")),
            font_path=self._build_data_uri(kwargs.get("font_path")),
            badges=kwargs.get("badges") or [],
            stats=kwargs.get("stats") or [],
            sections=kwargs.get("sections") or [],
            items=kwargs.get("items") or [],
            template_name=kwargs.get("template_name", "default"),
            card_width=card_width,
            card_min_height=int(kwargs.get("card_min_height", 360)),
        )

        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page(
                viewport={"width": max(card_width + 80, 640), "height": 1600},
                device_scale_factor=2,
            )
            await page.set_content(html, wait_until="load")
            root = page.locator("[data-card-root='true']").first
            if await root.count():
                png = await root.screenshot(type="png")
            else:
                png = await page.screenshot(full_page=True, type="png")
            await browser.close()

        return png
