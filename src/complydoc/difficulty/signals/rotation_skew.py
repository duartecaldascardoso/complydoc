"""Page rotation flag and estimated scan skew."""

from __future__ import annotations

import numpy as np

from complydoc.difficulty.base import Measurement
from complydoc.difficulty.registry import signal
from complydoc.ingest.base import Document, DocumentFormat

_ANGLE_LIMIT = 5.0
_ANGLE_STEP = 0.25
_ANALYSIS_WIDTH = 400


def _profile_score(ink: object, angle: float) -> float:
    """How strongly the horizontal ink profile peaks at this rotation.

    Level text lines produce alternating bands of ink and whitespace and so a
    spiky profile; sloped lines smear into a flat one. Using the coefficient of
    variation rather than raw variance keeps the number dimensionless, so scores
    from differently shaped images can be compared.
    """
    from PIL import Image as PILImage

    assert isinstance(ink, PILImage.Image)
    rotated = ink.rotate(angle, resample=PILImage.BILINEAR, fillcolor=0)
    profile = np.asarray(rotated, dtype=np.float32).sum(axis=1)
    mean = float(profile.mean())
    return float(profile.std()) / mean if mean > 0 else 0.0


def _best_angle(ink: object) -> tuple[float, float]:
    """The rotation in [-limit, +limit] that best levels the text, and its score."""
    best_angle, best_score = 0.0, -1.0
    for angle in np.arange(-_ANGLE_LIMIT, _ANGLE_LIMIT + _ANGLE_STEP, _ANGLE_STEP):
        score = _profile_score(ink, float(angle))
        if score > best_score:
            best_score, best_angle = score, float(angle)
    return best_angle, best_score


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
    if np.asarray(ink).sum() == 0:
        return None

    upright_angle, upright_score = _best_angle(ink)
    turned = ink.rotate(90, expand=True)
    turned_angle, turned_score = _best_angle(turned)

    if turned_score > upright_score:
        # A positive result means the page must be rotated by -angle to level it.
        return -turned_angle, 90
    return -upright_angle, 0


@signal
class PageRotationSignal:
    id = "page_rotation"
    name = "Page rotation flag"
    unit = "degrees"
    why = (
        "A page marked as rotated is stored sideways and only turned upright by the "
        "viewer. Tools that read the stored orientation instead of the displayed one get "
        "the layout, and therefore the reading order, completely wrong."
    )
    applies_to = frozenset({DocumentFormat.PDF, DocumentFormat.IMAGE})

    def measure(self, document: Document) -> Measurement:
        if not document.pages:
            return Measurement.na("the document could not be opened")
        rotations = [abs(p.rotation) % 360 for p in document.pages]
        worst = max(rotations)
        return Measurement(
            value=worst,
            display=f"{worst} degrees" if worst else "upright",
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
    why = (
        "A page fed through a scanner at an angle puts every text line on a slope. OCR "
        "accuracy falls away quickly with skew, and table row detection fails outright "
        "once lines cross each other's vertical bands."
    )
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
            display=f"{worst:+.2f} degrees at the worst page",
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
