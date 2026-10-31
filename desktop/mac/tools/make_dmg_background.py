#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 macOS 安装包 DMG 的窗口背景图（2 倍图，窗口 680x510）。

背景图上直接写明「首次打开被拦截 → 系统设置 → 隐私与安全性 → 仍要打开」的完整步骤，
用户挂载 DMG 一眼就能看到，不用去翻网页。
"""
import os

from PIL import Image, ImageDraw, ImageFont

FONT_CANDIDATES = [
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
]

S = 2                      # 2 倍图
W, H = 680, 510            # 逻辑尺寸（窗口大小）
IW, IH = W * S, H * S      # 实际像素

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "build", "dmg-background.png")


def load_font(size):
    for p in FONT_CANDIDATES:
        if os.path.isfile(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()


def fit_font(draw, text, size, max_w):
    """从给定字号往下缩，直到文本宽度不超过 max_w。"""
    while size > 12:
        f = load_font(size)
        if draw.textlength(text, font=f) <= max_w:
            return f
        size -= 1
    return load_font(12)


def main():
    img = Image.new("RGB", (IW, IH), "#ffffff")
    d = ImageDraw.Draw(img)

    # 竖向渐变背景
    top, bottom = (255, 255, 255), (233, 239, 248)
    for y in range(IH):
        r = y / max(IH - 1, 1)
        d.line([(0, y), (IW, y)],
               fill=tuple(int(top[i] + (bottom[i] - top[i]) * r) for i in range(3)))

    def cx(text, y, size, color, max_w=None, bold=False):
        f = fit_font(d, text, size, max_w or (IW - 80 * S))
        w = d.textlength(text, font=f)
        d.text(((IW - w) / 2, y * S), text, font=f, fill=color)
        return f

    # ---------- 标题区 ----------
    cx("教学管理系统", 40, 30, "#12307a")
    cx("把左边的图标拖进右边的「应用程序」文件夹即可安装", 78, 14, "#5b6579")

    # ---------- 拖拽箭头（图标由 Finder 自己画，这里只留箭头） ----------
    ay = 200 * S
    x1, x2 = 268 * S, 396 * S
    d.line([(x1, ay), (x2, ay)], fill="#9aa8bd", width=2 * S)
    d.polygon([(x2, ay), (x2 - 14 * S, ay - 7 * S), (x2 - 14 * S, ay + 7 * S)], fill="#9aa8bd")

    # ---------- 底部操作说明面板 ----------
    px0, py0, px1, py1 = 40 * S, 348 * S, (W - 40) * S, 494 * S
    d.rounded_rectangle([px0, py0, px1, py1], radius=14 * S,
                        fill="#fffbeb", outline="#fcd34d", width=2 * S)

    inner_max = int((px1 - px0) - 44 * S)
    lines = [
        (368, 15.5, "首次打开若提示「无法打开 / 已损坏」，按下面 3 步放行：", "#b45309"),
        (394, 13.5, "① 双击 App，弹窗里点「完成」（千万不要点「移到废纸篓」）", "#7c2d12"),
        (418, 13.5, "② 打开「系统设置 → 隐私与安全性」，向下拉到「安全性」一栏", "#7c2d12"),
        (442, 13.5, "③ 点右边的「仍要打开」→ 再点「打开」（需指纹或开机密码）", "#7c2d12"),
        (468, 12.0, "备选：终端执行  sudo xattr -cr /Applications/教学管理系统.app", "#a16207"),
    ]
    for y, size, text, color in lines:
        cx(text, y, int(size * S), color, max_w=inner_max)

    img.save(OUT)
    print("已生成：%s  %dx%d" % (OUT, IW, IH))

    # 自检：把每条文字的宽度打印出来，确认没有超出面板
    chk = ImageDraw.Draw(img)
    for y, size, text, _ in lines:
        f = fit_font(chk, text, int(size * S), inner_max)
        print("  %5.0fpx  %s" % (chk.textlength(text, font=f), text))


if __name__ == "__main__":
    main()
