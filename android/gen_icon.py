#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 App 图标：蓝色渐变圆角方块 + 白色粗体 NL。输出各分辨率 mipmap 图标。"""
import os
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(ROOT, "android", "app", "src", "main", "res")

SIZE = 1024
CORNER = 230          # 圆角半径（约 22%）
C_TOP = (90, 160, 248)     # 渐变浅蓝（左上）
C_BOTTOM = (43, 100, 224)  # 渐变深蓝（右下）


def rounded_gradient(size: int) -> Image.Image:
    """带圆角遮罩的对角线性渐变方块。"""
    # 渐变：沿左上→右下对角线插值
    grad = Image.new("RGBA", (size, size))
    px = grad.load()
    for y in range(size):
        for x in range(size):
            t = (x + y) / (2 * size - 2)
            r = int(C_TOP[0] + (C_BOTTOM[0] - C_TOP[0]) * t)
            g = int(C_TOP[1] + (C_BOTTOM[1] - C_TOP[1]) * t)
            b = int(C_TOP[2] + (C_BOTTOM[2] - C_TOP[2]) * t)
            px[x, y] = (r, g, b, 255)
    # 圆角遮罩
    mask = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(mask)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=CORNER, fill=255)
    grad.putalpha(mask)
    return grad


def find_font(size: int):
    """找系统粗体字体。"""
    candidates = [
        ("/System/Library/Fonts/Helvetica.ttc", 1),   # index 1 = Bold
        ("/System/Library/Fonts/HelveticaNeue.ttc", 1),
        ("/Library/Fonts/Arial Bold.ttf", 0),
        ("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 0),
    ]
    for path, idx in candidates:
        try:
            return ImageFont.truetype(path, size, index=idx)
        except Exception:
            continue
    return ImageFont.load_default()


def make_icon(size: int) -> Image.Image:
    icon = rounded_gradient(size)
    d = ImageDraw.Draw(icon)
    font = find_font(int(size * 0.42))
    text = "NL"
    bbox = d.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (size - tw) / 2 - bbox[0]
    y = (size - th) / 2 - bbox[1]
    d.text((x, y), text, font=font, fill=(255, 255, 255, 255))
    return icon


def main():
    full = make_icon(SIZE)
    full.save(os.path.join(ROOT, "icon-1024.png"))
    for dpi, px in (("mdpi", 48), ("hdpi", 72), ("xhdpi", 96), ("xxhdpi", 144), ("xxxhdpi", 192)):
        folder = os.path.join(RES, f"mipmap-{dpi}")
        os.makedirs(folder, exist_ok=True)
        full.resize((px, px), Image.LANCZOS).save(os.path.join(folder, "ic_launcher.png"))
        print(f"mipmap-{dpi}: {px}x{px} ok")
    print("icon-1024.png ok")


if __name__ == "__main__":
    main()
