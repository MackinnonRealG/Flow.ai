"""Generate AppIcon.icns for Flow: white mic on an indigo→violet squircle.

Run from app/:  uv run --with pillow python make-icon.py
Produces icon-master.png (preview), AppIcon.iconset/, and AppIcon.icns.
"""

import subprocess
from pathlib import Path

from PIL import Image, ImageDraw

S = 1024
HERE = Path(__file__).parent


def gradient(top: tuple, bottom: tuple) -> Image.Image:
    img = Image.new("RGB", (S, S))
    px = img.load()
    for y in range(S):
        t = y / (S - 1)
        color = tuple(round(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        for x in range(S):
            px[x, y] = color
    return img


def circle(draw: ImageDraw.ImageDraw, cx: float, cy: float, r: float, fill) -> None:
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fill)


def main() -> None:
    # Big Sur-style squircle: rounded rect, radius ≈ 23% of size
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], radius=236, fill=255)

    icon = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    icon.paste(gradient((79, 70, 229), (147, 51, 234)), (0, 0), mask)  # indigo → violet

    d = ImageDraw.Draw(icon)
    white = (255, 255, 255, 255)
    cx = S / 2

    # microphone capsule
    d.rounded_rectangle([cx - 105, 240, cx + 105, 590], radius=105, fill=white)

    # stand: open arc under the capsule
    arc_w = 42
    d.arc([cx - 195, 400, cx + 195, 790], start=20, end=160, fill=white, width=arc_w)
    # round the arc's ends
    import math
    for ang in (20, 160):
        r_mid = 195 - arc_w / 2
        ax = cx + r_mid * math.cos(math.radians(ang))
        ay = 595 + (390 / 2 - arc_w / 2) * 0  # unused; kept simple below
    # (arc box center-y is 595; compute endpoints on the mid-radius ellipse)
    exr, eyr = 195 - arc_w / 2, 195 - arc_w / 2
    for ang in (20, 160):
        ax = cx + (195 - arc_w / 2) * math.cos(math.radians(ang))
        ay = 595 + (195 - arc_w / 2) * math.sin(math.radians(ang))
        circle(d, ax, ay, arc_w / 2, white)

    # stem and base
    d.rounded_rectangle([cx - 21, 770, cx + 21, 858], radius=21, fill=white)
    d.rounded_rectangle([cx - 120, 850, cx + 120, 892], radius=21, fill=white)

    icon.save(HERE / "icon-master.png")

    # iconset for iconutil
    iconset = HERE / "AppIcon.iconset"
    iconset.mkdir(exist_ok=True)
    for base in (16, 32, 128, 256, 512):
        for scale in (1, 2):
            px = base * scale
            name = f"icon_{base}x{base}" + ("@2x" if scale == 2 else "") + ".png"
            icon.resize((px, px), Image.LANCZOS).save(iconset / name)

    subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(HERE / "AppIcon.icns")],
                   check=True)
    print("Wrote icon-master.png, AppIcon.iconset/, AppIcon.icns")


if __name__ == "__main__":
    main()
