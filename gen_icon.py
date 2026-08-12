# -*- coding: utf-8 -*-
"""生成 BLPowerBattery 应用图标 app.ico（电池 + 闪电）"""
from PIL import Image, ImageDraw

S = 256  # 画布尺寸


def draw_battery(size=S):
    # 4x 超采样抗锯齿
    scale = 4
    big = size * scale
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # 背景圆角托盘（半透明深色），让图标在浅色任务栏上也清晰
    d.rounded_rectangle([8 * scale, 8 * scale, big - 8 * scale, big - 8 * scale],
                        radius=46 * scale, fill=(28, 32, 40, 255))

    # 电池主体外框（白色圆角）
    bx0, by0, bx1, by1 = 46 * scale, 78 * scale, 196 * scale, 178 * scale
    d.rounded_rectangle([bx0, by0, bx1, by1], radius=22 * scale,
                        fill=(232, 238, 245, 255))
    # 电池内部深色
    pad = 8 * scale
    d.rounded_rectangle([bx0 + pad, by0 + pad, bx1 - pad, by1 - pad],
                        radius=16 * scale, fill=(24, 27, 34, 255))
    # 电池正极小凸起
    d.rounded_rectangle([bx1, by0 + 30 * scale, bx1 + 12 * scale, by1 - 30 * scale],
                        radius=6 * scale, fill=(232, 238, 245, 255))

    # 电量填充（绿色）
    fx0 = bx0 + pad + 4 * scale
    fy0 = by0 + pad + 4 * scale
    fx1 = bx0 + (bx1 - bx0) * 0.72
    fy1 = by1 - pad - 4 * scale
    d.rounded_rectangle([fx0, fy0, fx1, fy1], radius=12 * scale,
                        fill=(62, 224, 122, 255))

    # 闪电符号（黄色），居中偏右
    cx, cy = (bx0 + bx1) / 2 + 18 * scale, (by0 + by1) / 2
    bw = 26 * scale
    bh = 52 * scale
    bolt = [
        (cx + bw * 0.2, cy - bh * 0.5),
        (cx - bw * 0.5, cy + bh * 0.08),
        (cx - bw * 0.02, cy + bh * 0.08),
        (cx - bw * 0.2, cy + bh * 0.5),
        (cx + bw * 0.5, cy - bh * 0.08),
        (cx + bw * 0.02, cy - bh * 0.08),
    ]
    d.polygon(bolt, fill=(255, 216, 77, 255))

    img = img.resize((size, size), Image.LANCZOS)
    return img


def main():
    img = draw_battery(256)
    out = r"d:\MP\blpower\app.ico"
    img.save(out, sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    # PNG 预览，便于查看效果
    img.save(r"d:\MP\blpower\app_preview.png")
    print("saved:", out)


if __name__ == "__main__":
    main()
