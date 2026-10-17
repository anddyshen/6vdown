"""生成现代化、色彩鲜明通透的高清 6vdown 应用图标 (PNG + 多分辨率 ICO)。
蓝靛科技渐变 + 纯白立体高光播放三角 + 动感极速磁力下载条。
"""
import os
from PIL import Image, ImageDraw, ImageFilter

def create_modern_icon(size=512):
    # 画布
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))

    # 1. 柔和环境光阴影 (Drop Shadow)
    shadow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    s_draw = ImageDraw.Draw(shadow)
    margin = int(size * 0.08)
    corner = int(size * 0.22)
    s_box = [margin, margin + int(size * 0.04), size - margin, size - margin + int(size * 0.04)]
    s_draw.rounded_rectangle(s_box, radius=corner, fill=(15, 23, 42, 120))
    shadow = shadow.filter(ImageFilter.GaussianBlur(int(size * 0.035)))
    img.alpha_composite(shadow)

    # 2. 鲜明醒目的主卡片渐变 (深海蓝 -> 科技主蓝 -> 极光湖青: #1e3a8a -> #2563eb -> #0284c7)
    card = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    grad = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    grad_draw = ImageDraw.Draw(grad)
    for y in range(size):
        ratio = y / size
        if ratio < 0.5:
            r1 = ratio * 2
            r = int(30 * (1 - r1) + 37 * r1)
            g = int(58 * (1 - r1) + 99 * r1)
            b = int(138 * (1 - r1) + 235 * r1)
        else:
            r2 = (ratio - 0.5) * 2
            r = int(37 * (1 - r2) + 2 * r2)
            g = int(99 * (1 - r2) + 132 * r2)
            b = int(235 * (1 - r2) + 199 * r2)
        grad_draw.line([(0, y), (size, y)], fill=(r, g, b, 255))
    
    box = [margin, margin, size - margin, size - margin]
    card_mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(card_mask).rounded_rectangle(box, radius=corner, fill=255)
    card.paste(grad, (0, 0), card_mask)

    # 3. 边框微光描边
    border_layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(border_layer).rounded_rectangle(box, radius=corner, outline=(255, 255, 255, 80), width=max(2, int(size * 0.015)))
    card.alpha_composite(border_layer)

    # 4. 核心符号图层
    symbol = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    s_draw = ImageDraw.Draw(symbol)
    center_x = size * 0.48
    center_y = size * 0.44

    # (A) 纯白播放三角 (Play Triangle)
    tri_size = size * 0.19
    p1 = (center_x - tri_size * 0.65, center_y - tri_size * 0.85)
    p2 = (center_x + tri_size * 1.15, center_y)
    p3 = (center_x - tri_size * 0.65, center_y + tri_size * 0.85)
    s_draw.polygon([p1, p2, p3], fill=(255, 255, 255, 255))

    # (B) 动感磁力下载条 (Speed Bars)
    arrow_y = size * 0.72
    bars = [
        (size * 0.26, arrow_y - size * 0.07, size * 0.74, size * 0.038, (255, 255, 255, 250)),
        (size * 0.33, arrow_y, size * 0.67, size * 0.038, (125, 211, 252, 255)),
        (size * 0.41, arrow_y + size * 0.07, size * 0.59, size * 0.038, (56, 189, 248, 255)),
    ]
    for bx, by, bw, bh, color in bars:
        s_draw.rounded_rectangle([bx, by, bw, by + bh], radius=int(bh / 2), fill=color)

    # 合成符号
    card.alpha_composite(symbol)

    # 最终合成到带阴影画布
    img.alpha_composite(card)
    return img

def main():
    assets_dir = r"d:\Projects\c2down\assets"
    os.makedirs(assets_dir, exist_ok=True)
    
    base_img = create_modern_icon(512)
    
    # 保存高精度 PNG
    png_path = os.path.join(assets_dir, "6vdown.png")
    c2_png = os.path.join(assets_dir, "c2down.png")
    base_img.save(png_path, "PNG")
    base_img.save(c2_png, "PNG")
    print(f"Saved PNG to {png_path}")
    
    # 生成多尺寸包含的 Windows ICO (16, 24, 32, 48, 64, 128, 256)
    ico_sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    ico_path = os.path.join(assets_dir, "6vdown.ico")
    c2_ico = os.path.join(assets_dir, "c2down.ico")
    
    base_img.save(ico_path, format="ICO", sizes=ico_sizes)
    base_img.save(c2_ico, format="ICO", sizes=ico_sizes)
    print(f"Saved Multi-resolution ICO to {ico_path}")

if __name__ == "__main__":
    main()
