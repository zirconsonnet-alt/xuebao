import base64
import os
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont, ImageEnhance
from nonebot.adapters.onebot.v11 import MessageSegment


class CardMaker:
    def __init__(self, config):
        self.title = config.get('标题', '')
        self.text = config.get('文字', '')
        self.image_path = config.get('图片', 'background.jpg') or 'background.jpg'
        self.data_dir = 'data/nonebot_plugin_cardmaker'
        self.legacy_data_dir = os.path.join(self.data_dir, 'data')
        if os.path.isabs(self.image_path):
            self.background_path = self.image_path
        else:
            self.background_path = os.path.join(self.data_dir, self.image_path)
            if not os.path.exists(self.background_path):
                legacy_path = os.path.join(self.legacy_data_dir, self.image_path)
                if os.path.exists(legacy_path):
                    self.background_path = legacy_path
        self.font_name = 'CFDS.ttf'
        self.font_path = os.path.join(self.data_dir, self.font_name)
        if not os.path.exists(self.font_path):
            legacy_font = os.path.join(self.legacy_data_dir, self.font_name)
            if os.path.exists(legacy_font):
                self.font_path = legacy_font
        os.makedirs(self.data_dir, exist_ok=True)
        self.font_size = 27
        self.create_card()

    def create_card(self):
        target_width, target_height = 480, 360
        try:
            img = Image.open(self.background_path)
            if img.mode != 'RGB':
                img = img.convert('RGB')
        except IOError:
            img = Image.new('RGB', (target_width, target_height), (0, 255, 0))
        original_width, original_height = img.size
        target_ratio = target_width / target_height
        original_ratio = original_width / original_height
        if original_ratio > target_ratio:
            new_height = target_height
            new_width = int(new_height * original_ratio)
        else:
            new_width = target_width
            new_height = int(new_width / original_ratio)
        img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
        left = (new_width - target_width) // 2
        top = (new_height - target_height) // 2
        right = left + target_width
        bottom = top + target_height
        img = img.crop((left, top, right, bottom))
        draw = ImageDraw.Draw(img)
        try:
            title_font = ImageFont.truetype(self.font_path, 36)
            font = ImageFont.truetype(self.font_path, self.font_size)
        except IOError:
            title_font = ImageFont.load_default()
            font = ImageFont.load_default()
        title_bbox = draw.textbbox((0, 0), self.title, font=title_font)
        title_width = title_bbox[2] - title_bbox[0]
        title_x = (img.width - title_width) // 2
        title_y = 20
        for offset in [(1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, -1), (1, -1), (-1, 1)]:
            draw.text((title_x + offset[0], title_y + offset[1]), self.title, fill=(0, 0, 0), font=title_font)
        draw.text((title_x, title_y), self.title, fill=(255, 255, 255), font=title_font)
        lines = self.text.split('\n')
        line_height = draw.textbbox((0, 0), lines[0], font=font)[3] if lines else 0
        total_text_height = line_height * len(lines)
        max_line_width = max([draw.textbbox((0, 0), line, font=font)[2] for line in lines]) if lines else 0
        text_x = (img.width - max_line_width) // 2
        text_y = img.height - total_text_height - 30
        for line in lines:
            for offset in [(1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, -1), (1, -1), (-1, 1)]:
                draw.text((text_x + offset[0], text_y + offset[1]), line, fill=(0, 0, 0), font=font)
            draw.text((text_x, text_y), line, fill=(255, 255, 255), font=font)
            text_y += line_height
        buffered = BytesIO()
        img.save(buffered, format="PNG")
        img_base64 = base64.b64encode(buffered.getvalue()).decode('utf-8')
        return MessageSegment.image(BytesIO(base64.b64decode(img_base64)))


