#!/usr/bin/env python3
"""生成应用图标：assets/icon.png（全平台）、assets/icon.ico（Windows）。

macOS 的 .icns 需要 macOS 自带工具转换，见 packaging/build.py 中的说明
（sips + iconutil），CI 里已自动处理。

用法： python packaging/make_icon.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
SIZE = 1024

# Windows cp1252 控制台下打印中文会抛 UnicodeEncodeError（退出码 1 且无日志）
os.environ.setdefault("PYTHONUTF8", "1")
for _name in ("stdout", "stderr"):
    _stream = getattr(sys, _name, None)
    if _stream is not None:
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass

# B 站风格的粉色，但整体保持中性，避免与官方标识混淆
BG_TOP = (255, 122, 158)
BG_BOTTOM = (222, 55, 110)
ARROW = (255, 255, 255)
TRAY = (255, 255, 255, 210)


def _lerp(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def build_icon() -> Image.Image:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))

    # 渐变底 + 圆角（用蒙版裁切）
    gradient = Image.new("RGBA", (SIZE, SIZE))
    draw_grad = ImageDraw.Draw(gradient)
    for y in range(SIZE):
        draw_grad.line([(0, y), (SIZE, y)], fill=_lerp(BG_TOP, BG_BOTTOM, y / (SIZE - 1)) + (255,))

    radius = int(SIZE * 0.22)
    mask = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, SIZE - 1, SIZE - 1], radius=radius, fill=255)
    img.paste(gradient, (0, 0), mask)

    # 前景：向下的箭头 + 底座横线（下载语义）
    draw = ImageDraw.Draw(img)
    cx = SIZE // 2
    shaft_w = int(SIZE * 0.085)
    shaft_top = int(SIZE * 0.22)
    shaft_bottom = int(SIZE * 0.56)

    draw.rounded_rectangle(
        [cx - shaft_w // 2, shaft_top, cx + shaft_w // 2, shaft_bottom],
        radius=shaft_w // 2,
        fill=ARROW,
    )
    # 箭头三角
    head_half = int(SIZE * 0.145)
    head_top = shaft_bottom - int(SIZE * 0.02)
    head_bottom = int(SIZE * 0.72)
    draw.polygon(
        [(cx - head_half, head_top), (cx + head_half, head_top), (cx, head_bottom)],
        fill=ARROW,
    )
    # 底座（托盘）
    tray_h = int(SIZE * 0.055)
    tray_w = int(SIZE * 0.44)
    draw.rounded_rectangle(
        [cx - tray_w // 2, int(SIZE * 0.79), cx + tray_w // 2, int(SIZE * 0.79) + tray_h],
        radius=tray_h // 2,
        fill=TRAY,
    )
    return img


def main() -> int:
    ASSETS.mkdir(parents=True, exist_ok=True)
    icon = build_icon()

    png_path = ASSETS / "icon.png"
    icon.save(png_path, format="PNG")
    print(f"[完成] {png_path}")

    ico_path = ASSETS / "icon.ico"
    icon.save(
        ico_path,
        format="ICO",
        sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)],
    )
    print(f"[完成] {ico_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
