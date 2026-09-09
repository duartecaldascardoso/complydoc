"""Page rotation flag and estimated scan skew."""

from __future__ import annotations

from typing import NamedTuple

import numpy as np

from complydoc.difficulty.base import Measurement
from complydoc.difficulty.registry import signal
from complydoc.ingest.base import Document, DocumentFormat

_ANGLE_LIMIT = 5.0
_ANGLE_STEP = 0.25
_ANALYSIS_WIDTH = 400


class Ink(NamedTuple):
    """Where the ink is, centred on the page, and how tall the page is."""

    rows: np.ndarray
    columns: np.ndarray
    height: int

    def turned(self, width: int) -> Ink:
        """The same ink seen a quarter turn round.

        A turn is what the second orientation needs, and a turn is a swap of the
        axes with one of them negated. Swapping alone is a transpose, which is a
        reflection, and a reflection reports the skew with its sign flipped.
        """
        return Ink(-self.columns, self.rows, width)


def _ink_coordinates(ink: object) -> tuple[Ink, int] | None:
    """Row and column of every ink pixel, centred on the page, plus the height.

    The search below projects the same pixels at forty different angles. Doing
    that by rotating the whole image forty times spends its time on the blank
    paper, which is most of the page; carrying the ink alone is the same
    measurement over a tenth of the data.
    """
    array = np.asarray(ink, dtype=np.uint8)
    rows, columns = np.nonzero(array)
    if rows.size == 0:
        return None
    height, width = array.shape
    return (
        Ink(
            rows.astype(np.float32) - height / 2.0,
            columns.astype(np.float32) - width / 2.0,
            height,
        ),
        width,
    )


def _profile_score(ink: Ink, angle: float) -> float:
    """How strongly the horizontal ink profile peaks at this rotation.

    Level text lines produce alternating bands of ink and whitespace and so a
    spiky profile; sloped lines smear into a flat one. Using the coefficient of
    variation rather than raw variance keeps the number dimensionless, so scores
    from differently shaped images can be compared.

    Rotating the page and summing its rows is the same thing as summing the ink
    into the rows it would land in, which is what happens here. Ink that would
    fall off the page is dropped, as it is when the page is rotated in place.
    """
    rows, columns, height = ink
    radians = np.deg2rad(angle)
    landing = rows * np.cos(radians) - columns * np.sin(radians) + height / 2.0
    index = landing.astype(np.int32)
    index = index[(index >= 0) & (index < height)]
    if index.size == 0:
        return 0.0
    profile = np.bincount(index, minlength=height).astype(np.float32)
    mean = float(profile.mean())
    return float(profile.std()) / mean if mean > 0 else 0.0


_COARSE_STEP = 1.0
"""The first pass. The score curve has one broad peak, so a degree is fine enough
to find which degree it is in."""


def _best_angle(ink: Ink) -> tuple[float, float]:
    """The rotation in [-limit, +limit] that best levels the text, and its score.

    Coarse then fine: eleven angles to locate the peak, then the neighbourhood of
    the winner at the full step. Scanning every step across the whole range spent
    most of its work far from the answer.
    """

    def search(angles: np.ndarray) -> tuple[float, float]:
        best_angle, best_score = 0.0, -1.0
        for angle in angles:
            score = _profile_score(ink, float(angle))
            if score > best_score:
                best_score, best_angle = score, float(angle)
        return best_angle, best_score

    coarse, _ = search(np.arange(-_ANGLE_LIMIT, _ANGLE_LIMIT + _COARSE_STEP, _COARSE_STEP))
    low = max(-_ANGLE_LIMIT, coarse - _COARSE_STEP)
    high = min(_ANGLE_LIMIT, coarse + _COARSE_STEP)
    return search(np.arange(low, high + _ANGLE_STEP / 2, _ANGLE_STEP))


def _estimate_skew(image: object) -> tuple[float, int] | None:
    """Skew in degrees plus the quarter-turn it was measured in.

    A sideways scan has its text lines running vertically, where a horizontal ink
    projection sees no line structure at all and would report zero skew on a badly
    skewed page. Both orientations are therefore tried and the one with the
    stronger line structure wins, which is what a real deskewer does.
    """
    from PIL import Image as PILImage

    if not isinstance(image, PILImage.Image):
        return None
    grey = image.convert("L")
    if grey.width > _ANALYSIS_WIDTH:
        ratio = _ANALYSIS_WIDTH / grey.width
        grey = grey.resize((_ANALYSIS_WIDTH, max(1, int(grey.height * ratio))))

    ink = grey.point(lambda v: 255 if v < 160 else 0).convert("L")
    found = _ink_coordinates(ink)
    if found is None:
        return None
    upright, width = found

    upright_angle, upright_score = _best_angle(upright)
    turned_angle, turned_score = _best_angle(upright.turned(width))

    if turned_score > upright_score:
        # A positive result means the page must be rotated by -angle to level it.
        return -turned_angle, 90
    return -upright_angle, 0


@signal
class PageRotationSignal:
    id = "page_rotation"
    name = "Page rotation flag"
    unit = "degrees"
    why = "A page stored sideways reads in the wrong order unless the tool corrects it."
    applies_to = frozenset({DocumentFormat.PDF, DocumentFormat.IMAGE})

    def measure(self, document: Document) -> Measurement:
        if not document.pages:
            return Measurement.na("the document could not be opened")
        rotations = [abs(p.rotation) % 360 for p in document.pages]
        worst = max(rotations)
        return Measurement(
            value=worst,
            display=f"{worst}\u00b0" if worst else "upright",
            detail={
                "per_page": rotations,
                "rotated_pages": sum(1 for r in rotations if r),
            },
        )


@signal
class SkewAngleSignal:
    id = "skew_angle"
    name = "Estimated scan skew"
    unit = "degrees"
    why = "OCR accuracy drops quickly with skew, and table rows stop lining up."
    applies_to = frozenset({DocumentFormat.PDF, DocumentFormat.IMAGE})

    def measure(self, document: Document) -> Measurement:
        rasterised = [p for p in document.pages if p.raster is not None]
        if not rasterised:
            return Measurement.na(
                "no page was rasterised for this document, which happens when every page "
                "has a usable text layer and so is not a scan"
            )
        results = [r for r in (_estimate_skew(p.raster) for p in rasterised) if r is not None]
        if not results:
            return Measurement.na("the rasterised pages contained no detectable ink")
        angles = [angle for angle, _ in results]
        sideways = sum(1 for _, turn in results if turn)
        worst = max(angles, key=abs)
        return Measurement(
            value=round(abs(worst), 2),
            display=f"{worst:+.1f}\u00b0, worst page",
            detail={
                "per_page_degrees": [round(a, 2) for a in angles],
                "pages_measured": len(angles),
                "pages_measured_sideways": sideways,
                "method": (
                    f"horizontal ink projection, searched between "
                    f"{-_ANGLE_LIMIT} and {_ANGLE_LIMIT} degrees in {_ANGLE_STEP} degree "
                    f"steps, in both the upright and the quarter-turned orientation"
                ),
            },
        )
