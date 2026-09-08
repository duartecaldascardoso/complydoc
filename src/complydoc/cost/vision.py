"""Vision token counting.

Providers count image tokens in genuinely different ways: some tile the image and
charge per tile, some use a width-times-height formula, some charge a flat count
per image below a size threshold. All the constants live in pricing.yaml; this
module only knows how to apply the three shapes.

Adding a fourth shape means adding a function and one line in `_FORMULAS`.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

from complydoc.config.schema import (
    FlatVisionFormula,
    ResolutionPreset,
    TiledVisionFormula,
    VisionFormula,
    WidthHeightVisionFormula,
)

__all__ = ["RenderedSize", "rendered_size", "vision_tokens"]


@dataclass(frozen=True, slots=True)
class RenderedSize:
    width_px: int
    height_px: int


def rendered_size(width_pt: float, height_pt: float, preset: ResolutionPreset) -> RenderedSize:
    """Pixel dimensions a page would be sent at, for a given resolution setting.

    The long edge is rendered to the preset's pixel count and the aspect ratio is
    preserved. A PDF page is vector content, so any resolution is achievable; the
    preset is a choice about how much detail to pay for, not a limit imposed by
    the source.
    """
    if width_pt <= 0 or height_pt <= 0:
        return RenderedSize(0, 0)
    long_edge_pt = max(width_pt, height_pt)
    scale = preset.long_edge_px / long_edge_pt
    return RenderedSize(
        width_px=max(1, round(width_pt * scale)),
        height_px=max(1, round(height_pt * scale)),
    )


def _fit_within(width: int, height: int, max_long: int, max_short: int) -> tuple[int, int]:
    """Scale down (never up) so the long and short sides fit the given limits."""
    if width <= 0 or height <= 0:
        return width, height
    long_side, short_side = max(width, height), min(width, height)
    scale = min(1.0, max_long / long_side, max_short / short_side)
    return max(1, round(width * scale)), max(1, round(height * scale))


def _width_height_tokens(size: RenderedSize, formula: WidthHeightVisionFormula) -> int:
    if size.width_px <= 0 or size.height_px <= 0 or formula.divisor <= 0:
        return 0
    tokens = (size.width_px * size.height_px) / formula.divisor
    if formula.cap_tokens is not None:
        tokens = min(tokens, float(formula.cap_tokens))
    return round(tokens)


def _tiled_tokens(size: RenderedSize, formula: TiledVisionFormula) -> int:
    if size.width_px <= 0 or size.height_px <= 0 or formula.tile_px <= 0:
        return 0
    width, height = _fit_within(
        size.width_px, size.height_px, formula.max_long_side_px, formula.max_short_side_px
    )
    tiles = math.ceil(width / formula.tile_px) * math.ceil(height / formula.tile_px)
    return formula.base_tokens + tiles * formula.tile_tokens


def _flat_tokens(size: RenderedSize, formula: FlatVisionFormula) -> int:
    if size.width_px <= 0 or size.height_px <= 0:
        return 0
    threshold = formula.tile_above_px
    if threshold is None or (size.width_px <= threshold and size.height_px <= threshold):
        return formula.tokens_per_image
    tiles = math.ceil(size.width_px / threshold) * math.ceil(size.height_px / threshold)
    return tiles * (formula.tile_tokens or formula.tokens_per_image)


_FORMULAS: dict[str, Callable[[RenderedSize, object], int]] = {
    "width_height": _width_height_tokens,  # type: ignore[dict-item]
    "tiled": _tiled_tokens,  # type: ignore[dict-item]
    "flat_per_image": _flat_tokens,  # type: ignore[dict-item]
}


def vision_tokens(size: RenderedSize, formula: VisionFormula) -> int:
    """Image tokens for one page at one resolution, under one provider's formula."""
    handler = _FORMULAS.get(formula.kind)
    if handler is None:  # pragma: no cover - guarded by the discriminated union
        raise ValueError(f"no handler for vision formula kind {formula.kind!r}")
    return handler(size, formula)
