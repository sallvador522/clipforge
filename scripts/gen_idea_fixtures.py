"""Generate deterministic procedural fixture assets for the idea-to-video PoC.

These are LOCAL test fixtures (clearly labelled, procedural gradients), not
AI imagery and not a substitute for Muse Image scene assets in production.
"""

import json
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "contracts"))

W, H = 720, 1280
OUT = ROOT / "apps" / "web" / "public" / "idea-fixtures" / "assets"
OUT.mkdir(parents=True, exist_ok=True)


def vgradient(top: tuple, bottom: tuple) -> Image.Image:
    img = Image.new("RGB", (W, H))
    px = img.load()
    for y in range(H):
        t = y / (H - 1)
        px_line = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        for x in range(W):
            px[x, y] = px_line
    return img


def stars(draw: ImageDraw.ImageDraw, rng: random.Random, n: int) -> None:
    for _ in range(n):
        x, y = rng.randrange(W), rng.randrange(H)
        r = rng.choice([1, 1, 1, 2])
        b = rng.randrange(140, 256)
        draw.ellipse([x - r, y - r, x + r, y + r], fill=(b, b, 255))


def scene_space(rng: random.Random) -> Image.Image:
    img = vgradient((4, 6, 20), (10, 14, 44))
    d = ImageDraw.Draw(img)
    stars(d, rng, 320)
    d.ellipse([W // 2 - 120, H - 260, W // 2 + 120, H - 20], fill=(28, 80, 160), outline=(90, 160, 255), width=3)
    d.ellipse([W // 2 - 118, H - 258, W // 2 + 118, H - 22], outline=(150, 200, 255), width=1)
    return img


def scene_entry(rng: random.Random) -> Image.Image:
    img = vgradient((8, 10, 30), (60, 30, 60))
    d = ImageDraw.Draw(img)
    stars(d, rng, 200)
    d.ellipse([-260, H - 320, 260, H + 200], fill=(30, 90, 170))
    for i in range(5):
        y = 300 + i * 90
        d.line([60, y, 660, y - 160], fill=(255, 140 + i * 20, 60), width=10 - i)
    d.ellipse([300, 420, 420, 540], fill=(40, 30, 30), outline=(255, 180, 80), width=4)
    return img


def scene_impact(rng: random.Random) -> Image.Image:
    img = vgradient((20, 12, 12), (80, 40, 20))
    d = ImageDraw.Draw(img)
    d.rectangle([0, H - 320, W, H], fill=(35, 22, 16))
    for r, col in ((260, (255, 120, 40)), (170, (255, 180, 90)), (90, (255, 240, 210))):
        d.ellipse([W // 2 - r, H - 320 - r, W // 2 + r, H - 320 + r], outline=col, width=6)
    d.ellipse([W // 2 - 60, H - 380, W // 2 + 60, H - 260], fill=(255, 250, 235))
    return img


def scene_chart(rng: random.Random) -> Image.Image:
    img = vgradient((8, 10, 18), (16, 20, 36))
    d = ImageDraw.Draw(img)
    for gx in range(0, W, 60):
        d.line([gx, 0, gx, H], fill=(30, 38, 60))
    for gy in range(0, H, 60):
        d.line([0, gy, W, gy], fill=(30, 38, 60))
    return img


def main() -> None:
    rng = random.Random(20261103)
    builders = {"asset_space": scene_space, "asset_entry": scene_entry,
                "asset_impact": scene_impact, "asset_chart_bg": scene_chart}
    for asset_id, build in builders.items():
        path = OUT / f"{asset_id}.png"
        build(rng).save(path)
        print("wrote", path, path.stat().st_size)


if __name__ == "__main__":
    main()
