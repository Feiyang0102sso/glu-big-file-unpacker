import matplotlib.pyplot as plt
from PIL import Image, ImageDraw, ImageFont
import numpy as np
import random


def create_shooter_style_font():
    # 设置画布
    width, height = 1200, 800
    background_color = (20, 20, 20)  # 接近黑色的深灰
    text_color = (230, 230, 230)  # 灰白色

    image = Image.new('RGB', (width, height), background_color)
    draw = ImageDraw.Draw(image)

    # 尝试加载一个粗体字体 (系统自带的 DejaVu Sans Bold 作为替代，Impact 最佳但不一定有)
    try:
        # 在Colab/Linux环境中通常可用
        font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        font = ImageFont.truetype(font_path, 130)
    except:
        # 回退方案
        font = ImageFont.load_default()

    letters = "ABCDE\nFGHIJ\nKLMNO\nPQRST\nUVWXY\nZ"

    # 绘制基础文字
    # 为了模拟 Alien Shooter 的 Impact 风格，我们需要紧凑一点
    start_x = 50
    start_y = 50
    line_height = 140
    char_spacing = 130

    current_x = start_x
    current_y = start_y

    rows = letters.split('\n')

    for row_idx, row in enumerate(rows):
        current_x = start_x + (width - (len(row) * char_spacing)) // 2  # 居中
        for char_idx, char in enumerate(row):
            # 绘制字母
            # 稍微拉伸一点高度模拟 Condensed 效果 (通过重绘实现比较复杂，这里用标准比例)
            draw.text((current_x, current_y), char, font=font, fill=text_color)

            # --- 添加“战损”效果 (Procedural Damage) ---
            # 1. 随机切割线 (Slashing Cuts)
            # 模拟 S 和 H 的断裂感
            for _ in range(random.randint(1, 3)):
                cut_width = random.randint(2, 5)
                x1 = current_x + random.randint(0, 100)
                y1 = current_y + random.randint(0, 100)
                # 主要是对角线切割
                draw.line([(x1, y1), (x1 + 30, y1 - 30)], fill=background_color, width=cut_width)
                draw.line([(x1, y1), (x1 - 20, y1 + 20)], fill=background_color, width=cut_width)

            # 2. 边缘缺口 (Edge Chipping)
            for _ in range(random.randint(2, 5)):
                cx = current_x + random.choice([10, 90, 20, 80]) + random.randint(-10, 10)
                cy = current_y + random.choice([20, 100, 10, 110]) + random.randint(-10, 10)
                size = random.randint(5, 15)
                # 绘制不规则多边形作为缺口
                poly_points = [
                    (cx, cy),
                    (cx + size, cy + random.randint(-5, 5)),
                    (cx + random.randint(-5, 5), cy + size)
                ]
                draw.polygon(poly_points, fill=background_color)

            # 3. 横向断裂 (Horizontal Stencil for specific letters like S, B, E)
            if char in ['S', 'B', 'E', 'R', 'A', 'P']:
                hy = current_y + 65 + random.randint(-10, 10)
                hx = current_x - 5
                draw.line([(hx, hy), (hx + 100, hy)], fill=background_color, width=3)

            current_x += char_spacing

        current_y += line_height

    return image


# 生成并展示
img = create_shooter_style_font()
plt.figure(figsize=(12, 8))
plt.imshow(img)
plt.axis('off')
plt.title("Alien Shooter Style Font Concept (A-Z)", color='white')
plt.show()