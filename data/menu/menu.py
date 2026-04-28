from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from nonebot import on_command
from nonebot.params import CommandArg
from nonebot.adapters.onebot.v11 import Message
from src.plugins.tools import send_image, send_message, wait_for

IMAGES_PER_PAGE = 10
menu_path = Path(__file__).parent.parent.parent.parent / 'data' / 'menu'


menu_items = [
        ("*语音", "开启语音回复"),
        ("*文字", "开启文字回复"),
        ("*说 *", "语音发送指定内容"),

        ("*BGM开启/关闭", "开启或关闭bgm"),
        ("*HT开启/关闭", "改变回复随机性"),
        ("*撤回", "撤回雪豹的上一条消息"),

        ("*play *", "播放曲库中的音乐"),
        ("*曲库", "查看可以播放的音乐"),
        ("*生成和弦 *", "生成指定的和弦进行"),

        ("*show *", "展示图库中的图片"),
        ("*图库", "查看可以展示的图片"),
        ("*存图 *", "将图片存入图库"),

        ("*切换人格 *", "切换人格以及语音"),
        ("*人格列表", "查看可选的人格"),
        ("*切换模型 *", "切换雪豹的模型"),

        ("*设置昵称 *", "改变召唤方式"),
        ("*重置对话", "重置聊天记录"),
        ('', ''),

        ("游戏启动", "开始一把狼人杀游戏"),
        ("游戏结束", "关闭狼人杀游戏"),
        ("*狼人杀", "查看狼人杀排行榜"),

        ("*今日壁纸", "随机发送壁纸"),
        ("*今/昨日词云", "查看一段时间内的词云"),
        ("*今/昨日B话榜", "查看一段时间内B话榜"),

        ("*mc", "随机获取一张mc建筑图"),
        ("*塔罗牌(占卜)", "抽取塔罗牌或者牌阵"),
    ]


abstract = on_command('help', aliases={'菜单', '帮助'}, priority=5, block=True)


@abstract.handle()
async def _(arg: Message = CommandArg()):
    global menu_items
    if arg.extract_plain_text():
        return
    create_menu_image()
    path = menu_path / 'menu.png'
    await send_image(path)


def create_menu_image():
    # 设置图片尺寸
    width, height = 800, 1350
    # 定义背景图和保存路径
    background_image_path = menu_path / 'background.png'
    output_image_path = menu_path / 'menu.png'
    # 加载背景图片并调整大小
    background_image = Image.open(background_image_path).resize((width, height))
    # 在背景图片上创建一个新的绘制对象
    draw = ImageDraw.Draw(background_image)
    # 设置字体路径和大小
    font_path = menu_path / "CFDS.ttf"
    command_font = ImageFont.truetype(font_path, 30)        # 指令字体
    description_font = ImageFont.truetype(font_path, 20)    # 描述字体
    # 设置行间距和边距
    margin = 80         # 缩小边距
    top_margin = 200    # 调整顶部边距
    column_width = (width - 4 * margin) // 3
    block_height = 90   # 固定每个块的高度
    line_spacing = 5    # 行间距
    # 文字位置起点
    x1, y1 = margin, top_margin
    x2, y2 = margin + column_width + margin, top_margin
    x3, y3 = margin + 2 * (column_width + margin), top_margin
    # 绘制文字
    for i, (command, description) in enumerate(menu_items):
        if i % 3 == 0:
            x, y = x1, y1
        elif i % 3 == 1:
            x, y = x2, y2
        else:
            x, y = x3, y3
        # 绘制指令
        draw.text((x, y), command, font=command_font, fill='black')
        y += 40     # 假设指令文本的高度为30像素
        # 自动换行描述
        description_lines = get_text_height_and_wrap_text(description, description_font, draw, column_width)
        # 确保描述文本为三行
        for line in description_lines[:3]:
            draw.text((x, y), line, font=description_font, fill='black')
            y += 20             # 每行文本的高度约为20像素
            y += line_spacing   # 增加行间距
        # 更新对应列的 y 坐标
        if i % 3 == 0:
            y1 += block_height
        elif i % 3 == 1:
            y2 += block_height
        else:
            y3 += block_height
    # 保存图片到指定路径
    background_image.save(output_image_path)


def get_text_height_and_wrap_text(text, font, draw, max_width):
    lines = []
    words = text.split(' ')
    current_line = ''
    for word in words:
        test_line = f'{current_line} {word}' if current_line else word
        width = draw.textbbox((0, 0), test_line, font=font)[2]
        if width <= max_width:
            current_line = test_line
        else:
            if current_line:
                lines.append(current_line)
            current_line = word
    if current_line:
        lines.append(current_line)
    return lines  # 返回换行后的文本行


def create_custom_image(header_text, items, footer_text, size=1):
    # 设置图片尺寸
    width, height = 800, 1000
    # 定义背景图和保存路径
    background_image_path = menu_path / 'background2.png'
    output_image_path = menu_path / 'custom_menu.png'
    # 加载背景图片并调整大小
    background_image = Image.open(background_image_path).resize((width, height))
    # 在背景图片上创建一个新的绘制对象
    draw = ImageDraw.Draw(background_image)
    # 设置字体路径和大小
    font_path = "simhei.ttf"  # 确保这个路径正确
    header_font = ImageFont.truetype(font_path, 60)  # 头部提示文字字体
    item_font = ImageFont.truetype(font_path, 40*size)  # 列表项字体
    footer_font = ImageFont.truetype(font_path, 30)  # 底部提示文字字体
    # 设置文字位置和行间距
    margin = 100  # 边距
    line_spacing = 20  # 行间距
    # 绘制头部提示文字
    header_bbox = draw.textbbox((0, 0), header_text, font=header_font)
    header_x = (width - header_bbox[2]) // 2
    header_y = margin
    draw.text((header_x, header_y), header_text, font=header_font, fill='black')
    # 绘制文字列表
    list_y = header_y + 80  # 列表项开始的 y 坐标
    for item in items:
        item_bbox = draw.textbbox((0, 0), item, font=item_font)
        draw.text((margin, list_y), item, font=item_font, fill='black')
        list_y += item_bbox[3] - item_bbox[1] + line_spacing  # 更新 y 坐标以绘制下一行
    # 绘制底部提示文字
    footer_bbox = draw.textbbox((0, 0), footer_text, font=footer_font)
    footer_x = (width - footer_bbox[2]) // 2
    footer_y = height - margin - (footer_bbox[3] - footer_bbox[1])
    draw.text((footer_x, footer_y), footer_text, font=footer_font, fill='black')
    # 保存图片到指定路径
    background_image.save(output_image_path)
    return output_image_path


# 展示文件列表并处理用户输入
async def handle_file_request(arg: Message, directory: Path, file_exts: set, show_files_func, no_files_message: str):
    # 确保消息只包含此指令
    if arg.extract_plain_text():
        return
    # 获取文件列表
    files = [f.name for f in directory.glob("*") if f.suffix.lower() in file_exts]
    # 目录下还没有任何文件
    if not files:
        await send_message(no_files_message)
    # 计算总页数
    total_pages = (len(files) + IMAGES_PER_PAGE - 1) // IMAGES_PER_PAGE
    # 展示第一页菜单
    await show_files_func(files, 1, total_pages)
    # 等待用户输入页面号码
    while True:
        msg = await wait_for(10)
        if not msg:
            break
        if msg.isdigit() and 0 < int(msg) <= total_pages:
            await show_files_func(files, int(msg), total_pages)
        else:
            break


async def show_files(files, page_number, total_pages, media_type: str):
    """根据页码展示文件列表并生成相应的图片"""
    # 计算当前页的文件
    start_index = (page_number - 1) * IMAGES_PER_PAGE
    end_index = start_index + IMAGES_PER_PAGE
    page_files = files[start_index:end_index]
    if not page_files:
        return f"没有找到{media_type}。"
    # 生成文件列表文本
    files_list = [f"{i + 1}. {name}" for i, name in enumerate(page_files, start_index)]
    # 调用生成图片的函数
    header_text = f"第 {page_number} 页的{media_type}菜单"
    footer_text = f"输入页码可查看列表({page_number}/{total_pages})。\n如需退出菜单，请输入“退出”。"
    path = create_custom_image(header_text, files_list, footer_text)
    # 发送生成的图片
    await send_image(path)
    return None
