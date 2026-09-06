"""生成 assets/6vdown.ico（多尺寸）。依赖 Pillow，仅打包期使用。

用法：python tools/gen_icon.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image, ImageDraw  # noqa: E402

ACCENT = (37, 99, 235, 255)
GRAY = (154, 160, 166, 255)
WHITE = (255, 255, 255, 255)


def draw(size: int, gray: bool = False) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    base = GRAY if gray else ACCENT
    r = int(size * 0.22)
    d.rounded_rectangle([1, 1, size - 2, size - 2], radius=r, fill=base)
    # 播放三角
    d.polygon([(int(size * 0.36), int(size * 0.30)),
               (int(size * 0.68), int(size * 0.46)),
               (int(size * 0.36), int(size * 0.62))], fill=WHITE)
    # 底横条
    for i, w in enumerate((0.34, 0.5, 0.66)):
        y = int(size * 0.76 + i * size * 0.06)
        x0, x1 = int(size * 0.24), int(size * 0.24 + size * w * 0.9)
        d.line([(x0, y), (x1, y)], fill=WHITE,
               width=max(2, int(size * 0.055)))
    return img


def main() -> None:
    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "assets")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "6vdown.ico")
    img = draw(256)
    img.save(path, sizes=[(256, 256), (128, 128), (64, 64), (48, 48),
                          (32, 32), (16, 16)])
    # 同时导出 PNG（供文档）
    img.save(os.path.join(out_dir, "6vdown.png"))
    print("已生成:", path)


if __name__ == "__main__":
    main()
