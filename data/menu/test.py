from PIL import Image

def stretch_image(input_path, output_path, scale_factor=1.2):
    # 打开原始图片
    original_image = Image.open(input_path)
    
    # 获取原始图片尺寸
    original_width, original_height = original_image.size
    
    # 计算新的尺寸
    new_width = int(original_width)
    new_height = int(original_height * scale_factor)
    
    # 拉伸图片
    stretched_image = original_image.resize((new_width, new_height), Image.LANCZOS)
    
    # 保存拉伸后的图片
    stretched_image.save(output_path)

# 使用示例
input_image_path = 'background.png'  # 替换为实际的输入图片路径
output_image_path = 'output_image.png'  # 替换为实际的输出图片路径
stretch_image(input_image_path, output_image_path)
