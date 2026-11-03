"""Idea-to-video pricing and cost estimates.

Prices are advisory configuration, not a billing engine: the hard limit is the
per-job approval recorded on the job. Nothing here performs a network call.

Environment overrides (all optional, USD):
    CLIPFORGE_PRICE_STORYBOARD_USD   default 0.002
    CLIPFORGE_PRICE_STORYBOARD_HIGH_USD  default 0.01 (uncalibrated ceiling
        for the high reasoning effort; replaced once the first high call
        is measured — the ledger's recorded usage stays source of truth)
    CLIPFORGE_PRICE_STORYBOARD_XHIGH_USD  default 0.02 (uncalibrated ceiling
        for the xhigh reasoning effort; replaced once the first xhigh call
        is measured — the ledger's recorded usage stays source of truth)
    CLIPFORGE_PRICE_IMAGE_USD        default 0.01
    CLIPFORGE_IDEA_CAP_USD           default 0.10
"""

from __future__ import annotations

import os

from clipforge_contracts.idea import CostEstimate, IdeaOptions, scene_count_for
from clipforge_contracts.storyboard import Storyboard

DEFAULT_STORYBOARD_USD = 0.002
DEFAULT_STORYBOARD_HIGH_USD = 0.01
DEFAULT_STORYBOARD_XHIGH_USD = 0.02
DEFAULT_IMAGE_USD = 0.01
DEFAULT_CAP_USD = 0.10


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value >= 0 else default


def storyboard_price_usd(effort: str = "medium") -> float:
    if effort == "xhigh":
        return _env_float("CLIPFORGE_PRICE_STORYBOARD_XHIGH_USD", DEFAULT_STORYBOARD_XHIGH_USD)
    if effort == "high":
        return _env_float("CLIPFORGE_PRICE_STORYBOARD_HIGH_USD", DEFAULT_STORYBOARD_HIGH_USD)
    return _env_float("CLIPFORGE_PRICE_STORYBOARD_USD", DEFAULT_STORYBOARD_USD)


def image_price_usd() -> float:
    return _env_float("CLIPFORGE_PRICE_IMAGE_USD", DEFAULT_IMAGE_USD)


def cap_usd() -> float:
    return _env_float("CLIPFORGE_IDEA_CAP_USD", DEFAULT_CAP_USD)


def estimate_before_plan(
    options: IdeaOptions,
    *,
    director_mode: str,
    image_mode: str,
    effort: str = "medium",
) -> CostEstimate:
    """Upper-bound estimate shown before the storyboard exists.

    In mock mode the unit prices are zero (no provider is billed), but the
    planned image count is still reported so the UI can explain the flow.
    """
    planned_images = scene_count_for(options.duration_seconds) if options.use_generated_images else 0
    storyboard_usd = storyboard_price_usd(effort) if director_mode == "live" else 0.0
    images_usd = planned_images * image_price_usd() if image_mode == "live" else 0.0
    return CostEstimate(
        storyboard_usd=storyboard_usd,
        images_usd=round(images_usd, 6),
        total_usd=round(storyboard_usd + images_usd, 6),
        cap_usd=cap_usd(),
        image_count=planned_images,
    )


def estimate_from_storyboard(
    board: Storyboard,
    options: IdeaOptions,
    *,
    director_mode: str,
    image_mode: str,
    effort: str = "medium",
    selected_assets: int | None = None,
) -> CostEstimate:
    """Exact estimate once the board exists.

    `selected_assets` lets the review screen price only the plates the user
    kept checked. Without it, every planned plate is priced.
    """
    planned = len(board.asset_plan) if options.use_generated_images else 0
    count = planned if selected_assets is None else max(0, min(selected_assets, planned))
    storyboard_usd = storyboard_price_usd(effort) if director_mode == "live" else 0.0
    images_usd = count * image_price_usd() if image_mode == "live" else 0.0
    return CostEstimate(
        storyboard_usd=storyboard_usd,
        images_usd=round(images_usd, 6),
        total_usd=round(storyboard_usd + images_usd, 6),
        cap_usd=cap_usd(),
        image_count=count,
    )


def asset_cost_usd(count: int, *, image_mode: str) -> float:
    if image_mode != "live":
        return 0.0
    return round(max(0, count) * image_price_usd(), 6)
