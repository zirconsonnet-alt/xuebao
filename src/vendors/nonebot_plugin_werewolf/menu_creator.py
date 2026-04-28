from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from nonebot.internal.matcher import Matcher
from nonebot.adapters.onebot.v11 import MessageSegment


class WerewolfMenuCreator:
    IMAGES_PER_PAGE = 20

    def __init__(self, matcher: Matcher):
        self.menu_path = Path('data') / 'nonebot_plugins_werewolf' / 'menu'
        self.menu_path.mkdir(parents=True, exist_ok=True)
        self.matcher = matcher

    def create_werewolf_menu_image(self, players):
        width, height = 800, 1000
        output_image_path = self.menu_path / 'player_menu_page.png'
        background_image_path = self.menu_path / 'picture_menu.png'
        background_image = Image.open(background_image_path).resize((width, height))
        draw = ImageDraw.Draw(background_image)
        font_path = self.menu_path / "CFDS.ttf"
        header_font = ImageFont.truetype(font_path, 50)
        item_font = ImageFont.truetype(font_path, 30)
        footer_font = ImageFont.truetype(font_path, 25)
        margin = 50
        line_spacing = 10
        header_text = f"本群狼人杀排行榜"
        header_bbox = draw.textbbox((0, 0), header_text, font=header_font)
        header_x = (width - header_bbox[2]) // 2
        header_y = margin + 40
        draw.text((header_x, header_y), header_text, font=header_font, fill='black')
        title_text = "序号 | 昵称 | 总场次 | 胜场 | 胜率"
        title_bbox = draw.textbbox((0, 0), title_text, font=item_font)
        title_x = (width - title_bbox[2]) // 2
        draw.text((title_x, header_y + 60), title_text, font=item_font, fill='black')
        list_y = header_y + 100
        for index, (player_id, player_name, total_games, wins, losses, win_rate, rank) in enumerate(players):
            win_rate_percentage = f"{int(win_rate * 100)}%"
            if len(player_name) > 4:
                player_name = player_name[:4] + "..."
            index_width = 40
            name_width = 100
            total_width = 60
            win_width = 60
            rate_width = 60
            index_x = 120
            name_x = index_x + index_width + 20
            total_x = name_x + name_width + 60
            win_x = total_x + total_width + 20
            rate_x = win_x + win_width + 40
            index_block = f"{index + 1:<{index_width}}"
            player_name_block = f"{player_name:<{name_width}}"
            total_games_block = f"{total_games:<{total_width}}"
            win_count_block = f"{wins:<{win_width}}"
            win_rate_block = f"{win_rate_percentage:<{rate_width}}"
            draw.text((index_x, list_y), index_block, font=item_font, fill='black')
            draw.text((name_x, list_y), player_name_block, font=item_font, fill='black')
            draw.text((total_x, list_y), total_games_block, font=item_font, fill='black')
            draw.text((win_x, list_y), win_count_block, font=item_font, fill='black')
            draw.text((rate_x, list_y), win_rate_block, font=item_font, fill='black')
            item_bbox = draw.textbbox((0, 0), index_block, font=item_font)
            list_y += item_bbox[3] - item_bbox[1] + line_spacing
        footer_text = "榜单只显示前20名"
        footer_bbox = draw.textbbox((0, 0), footer_text, font=footer_font)
        footer_x = (width - footer_bbox[2]) // 2
        draw.text((footer_x, height - margin - 60), footer_text, font=footer_font, fill='black')
        background_image.save(output_image_path)
        return output_image_path

    async def show_top_players(self, players):
        players = players[:WerewolfMenuCreator.IMAGES_PER_PAGE]
        image_path = self.create_werewolf_menu_image(players)
        await self.matcher.send(MessageSegment.image(image_path))
