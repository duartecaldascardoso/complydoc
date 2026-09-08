"""Area coverage helpers shared by the ingest layer and the difficulty signals."""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np

from complydoc.ingest.base import Rect

__all__ = ["coverage_fraction"]


def coverage_fraction(rects: Iterable[Rect], width: float, height: float, grid: int = 240) -> float:
    """Fraction of the page covered by `rects`, in the range 0.0 to 1.0.

    Rasterises onto a coarse grid rather than summing areas, because text and
    image boxes overlap constantly and a naive sum reports coverage above 100%.
    """
    if width <= 0 or height <= 0:
        return 0.0
    boxes = [r for r in rects if r.area > 0]
    if not boxes:
        return 0.0

    mask = np.zeros((grid, grid), dtype=bool)
    for rect in boxes:
        col0 = int(np.clip(rect.x0 / width * grid, 0, grid))
        col1 = int(np.ceil(np.clip(rect.x1 / width * grid, 0, grid)))
        row0 = int(np.clip(rect.y0 / height * grid, 0, grid))
        row1 = int(np.ceil(np.clip(rect.y1 / height * grid, 0, grid)))
        if col1 > col0 and row1 > row0:
            mask[row0:row1, col0:col1] = True
    return float(mask.sum()) / float(grid * grid)
