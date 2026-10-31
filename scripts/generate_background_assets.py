"""Generate deterministic local mock background images (ADR-004). No external calls.

These are simple warm studio-like gradients generated with Pillow. They are
mock assets, clearly labelled as such, standing in for future generated media.
"""

from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1] / "assets" / "backgrounds"


def _studio(width: int, height: int) -> np.ndarray:
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float64)
    glow = np.exp(-(((xx - width * 0.5) / (width * 0.45)) ** 2 + ((yy - height * 0.38) / (height * 0.5)) ** 2))
    base = np.zeros((height, width, 3), dtype=np.float64)
    base[..., 0] = 38 + 70 * glow  # warm dark backdrop
    base[..., 1] = 32 + 48 * glow
    base[..., 2] = 28 + 30 * glow
    floor = yy > height * 0.78
    base[floor] += np.array([10, 8, 6])
    return np.clip(base, 0, 255).astype(np.uint8)


def main() -> int:
    ROOT.mkdir(parents=True, exist_ok=True)
    for name, w, h in [("studio_landscape.png", 1280, 720), ("studio_portrait.png", 720, 1280)]:
        out = ROOT / name
        Image.fromarray(_studio(w, h)).save(out)
        print(f"generated {out} ({w}x{h})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
