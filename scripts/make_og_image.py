#!/usr/bin/env python3
"""Generate app/static/og-image.png (1200x630) — the Open Graph/Twitter
preview card for the Global News Map (SMA-549). Dark theme matching the
site, wireframe globe + wordmark + tagline. Run: python3 scripts/make_og_image.py
"""
import math
import os
from PIL import Image, ImageDraw, ImageFont

W, H = 1200, 630
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "..", "app", "static", "og-image.png")

BG_TOP = (11, 18, 32)
BG_BOT = (16, 31, 58)
ACCENT = (56, 189, 248)
INK = (237, 243, 252)
MUTED = (147, 165, 194)


def background():
    """Per-pixel: vertical gradient + two smooth radial glows."""
    glows = [(950, 80, 420, 0.16), (300, 330, 290, 0.12)]
    im = Image.new("RGB", (W, H))
    px = im.load()
    for y in range(H):
        t = y / (H - 1)
        base = [BG_TOP[i] + (BG_BOT[i] - BG_TOP[i]) * t for i in range(3)]
        for x in range(W):
            g = 0.0
            for gx, gy, gr, gs in glows:
                dd = math.hypot(x - gx, y - gy) / gr
                if dd < 1.0:
                    g += gs * (1.0 - dd) ** 2
            c = tuple(min(255, int(base[i] + ACCENT[i] * g)) for i in range(3))
            px[x, y] = c
    return im


def wire_globe(d, cx, cy, r, line):
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=line, width=7)
    for lon in (-60, -30, 30, 60):
        w = int(abs(r * math.cos(math.radians(lon))))
        d.ellipse([cx - w, cy - r, cx + w, cy + r], outline=line, width=3)
    for lat in (-45, -22.5, 22.5, 45):
        y = cy + int(r * math.sin(math.radians(lat)))
        half = int(r * math.cos(math.radians(lat)))
        d.line([cx - half, y, cx + half, y], fill=line, width=3)


def main():
    im = background()
    d = ImageDraw.Draw(im)
    wire_globe(d, 285, 330, 170, ACCENT)

    fb = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    fr = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

    tx = 530
    max_w = W - 40 - tx
    size = 92
    while size > 40:
        f = ImageFont.truetype(fb, size)
        if d.textlength("Global News Map", font=f) <= max_w:
            break
        size -= 4
    f_title = ImageFont.truetype(fb, size)
    sub_lines = [
        "Today\u2019s headlines from 233 local news",
        "outlets across 141 countries",
        "\u2014 updated daily on the map",
    ]
    sub_size = 37
    f_sub = ImageFont.truetype(fr, sub_size)
    while sub_size > 20 and max(
        d.textlength(line, font=f_sub) for line in sub_lines
    ) > max_w:
        sub_size -= 2
        f_sub = ImageFont.truetype(fr, sub_size)

    d.text((tx, 200), "Global News Map", font=f_title, fill=INK)
    d.rectangle([tx, 200 + size + 12, tx + 130, 200 + size + 20], fill=ACCENT)
    y = 200 + size + 44
    for line in sub_lines:
        d.text((tx, y), line, font=f_sub, fill=MUTED)
        y += sub_size + 14

    im.save(OUT, "PNG")
    print("wrote", OUT, im.size, "title size", size)


if __name__ == "__main__":
    main()
