"""Programmatic animated backdrops (ADR-052 Magic Background).

A fully local, deterministic replacement background: vertical gradient +
animated vector shapes (circles, rings, bars, lines) rendered per frame with
real OpenCV/PIL. No AI call, no image generation, no network.

Every frame is a pure function of (t_seconds, width, height, spec): the same
inputs always produce the same pixels, so the Studio preview (verified MP4)
and the export share the exact composition by construction. Motion is gentle
sinusoidal drift scaled by spec.motion (subtle/moderate).
"""

from __future__ import annotations

import math
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw


def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    return (int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16))


def _motion_scale(motion: str) -> float:
    return 1.0 if motion == "moderate" else 0.45


def _vertical_gradient(width: int, height: int, top: tuple[int, int, int],
                       bottom: tuple[int, int, int], t: float, sway: float) -> np.ndarray:
    """BGR gradient with a slow diagonal light sway (deterministic in t)."""
    ys = np.linspace(0.0, 1.0, height, dtype=np.float32)[:, None, None]
    top_arr = np.array(top, dtype=np.float32).reshape(1, 1, 3)
    bottom_arr = np.array(bottom, dtype=np.float32).reshape(1, 1, 3)
    frame = top_arr * (1.0 - ys) + bottom_arr * ys
    xs = np.linspace(0.0, 1.0, width, dtype=np.float32)[None, :, None]
    glow_x = 0.5 + 0.28 * math.sin(t * 0.35) * sway
    glow = np.exp(-((xs - glow_x) ** 2) / 0.08).astype(np.float32)
    glow = np.broadcast_to(glow, (height, width, 3))
    frame = np.clip(frame + glow * 14.0, 0, 255)
    return frame.astype(np.uint8)


def _draw_shapes(canvas: Image.Image, draw: ImageDraw.ImageDraw, t: float,
                 width: int, height: int, shapes: list[dict[str, Any]], sway: float) -> None:
    unit = min(width, height)
    for index, shape in enumerate(shapes):
        kind = shape.get("kind", "circle")
        color = shape.get("color", "#FFFFFF")
        size = float(shape.get("size", 0.12))
        speed = float(shape.get("speed", 0.5))
        phase = float(shape.get("phase", 0.0))
        r, g, b = _hex_to_rgb(color)
        amp = unit * 0.10 * sway
        cx = width * (0.5 + 0.32 * math.sin(t * speed + phase + index * 1.7))
        cy = height * (0.5 + 0.26 * math.cos(t * speed * 0.8 + phase + index * 2.3))
        if kind == "circle":
            radius = max(2, int(unit * size * (1.0 + 0.08 * math.sin(t * speed * 1.3 + phase) * sway)))
            draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius],
                         fill=(r, g, b, 255))
        elif kind == "ring":
            radius = max(4, int(unit * size * (1.0 + 0.15 * math.sin(t * speed + phase) * sway)))
            thick = max(2, int(unit * 0.012))
            draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius],
                         outline=(r, g, b, 255), width=thick)
        elif kind == "bar":
            length = int(width * (0.25 + size))
            thick = max(3, int(unit * 0.03))
            drift = int(amp * math.sin(t * speed + phase))
            draw.rounded_rectangle([cx - length / 2 + drift, cy - thick / 2,
                                    cx + length / 2 + drift, cy + thick / 2],
                                   radius=thick // 2, fill=(r, g, b, 255))
        elif kind == "line":
            drift = int(amp * 1.4 * math.sin(t * speed * 0.7 + phase))
            draw.line([drift, 0, width * 0.6 + drift, height], fill=(r, g, b, 255),
                      width=max(2, int(unit * 0.008)))


def spec_from_contract(spec: Any) -> dict[str, Any]:
    """Normalize a ProgrammaticBackdrop (contract or dict) to plain values."""
    if hasattr(spec, "model_dump"):
        spec = spec.model_dump(mode="json")
    if not isinstance(spec, dict):
        raise ValueError("Programmatic backdrop spec must be a mapping.")
    top = str(spec.get("gradient_top", "#0B1E3A"))
    bottom = str(spec.get("gradient_bottom", "#123B7A"))
    shapes = spec.get("shapes") or []
    if not isinstance(shapes, list):
        raise ValueError("Programmatic backdrop shapes must be a list.")
    motion = str(spec.get("motion", "subtle"))
    if motion not in ("subtle", "moderate"):
        raise ValueError("Programmatic backdrop motion must be subtle or moderate.")
    return {"gradient_top": top, "gradient_bottom": bottom,
            "shapes": shapes, "motion": motion}


def render_frame(t: float, width: int, height: int, spec: Any) -> np.ndarray:
    """Render one BGR backdrop frame. Pure function of (t, W, H, spec)."""
    if width <= 0 or height <= 0:
        raise ValueError("Backdrop canvas must be positive.")
    norm = spec_from_contract(spec)
    sway = _motion_scale(norm["motion"])
    top = _hex_to_rgb(norm["gradient_top"])
    bottom = _hex_to_rgb(norm["gradient_bottom"])
    # Work in RGB for PIL, return BGR for the OpenCV pipeline.
    rgb = _vertical_gradient(width, height, top, bottom, t, sway)
    canvas = Image.fromarray(rgb).convert("RGBA")
    draw = ImageDraw.Draw(canvas, "RGBA")
    _draw_shapes(canvas, draw, t, width, height, norm["shapes"], sway)
    return cv2.cvtColor(np.array(canvas.convert("RGB")), cv2.COLOR_RGB2BGR)
