"""The optional weighted score.

The breakdown is the product; this is a convenience on top of it. The score is
only produced when every weight that went into it is printed alongside it, which
the config schema enforces rather than trusts.

Weights are renormalised over the signals that actually produced a rating for
this document, so a document where six signals do not apply is not silently
penalised for the six missing contributions.
"""

from __future__ import annotations

from dataclasses import dataclass

from complydoc.config.schema import ScoringConfig
from complydoc.readiness.base import SignalResult
from complydoc.text import count

__all__ = ["ReadinessScore", "ScoreComponent", "band_label", "compute_score"]


@dataclass(frozen=True, slots=True)
class ScoreComponent:
    signal_id: str
    name: str
    rating: str
    raw_weight: float
    normalised_weight: float
    points: float
    contribution: float


@dataclass(frozen=True, slots=True)
class ReadinessScore:
    value: float
    """0 (nothing can be read from it) to 100 (ready to process as it stands)."""
    label: str
    components: list[ScoreComponent]
    signals_counted: int
    signals_excluded: int
    method: str
    low_confidence: bool
    """True when most signals could not be measured, so the score rests on few lines."""
    confidence_note: str | None


def band_label(value: float) -> str:
    """The band, worded so that it reads the same way round as the number.

    The score used to be called difficulty while a high one meant easy, so both
    the name and half the labels ran against the scale.
    """
    if value >= 75:
        return "ready"
    if value >= 50:
        return "workable"
    if value >= 25:
        return "needs work"
    return "not ready"


def compute_score(results: list[SignalResult], config: ScoringConfig) -> ReadinessScore | None:
    if not config.enabled:
        return None

    counted = [r for r in results if r.counts_towards_score and r.weight > 0]
    excluded = len(results) - len(counted)
    if not counted:
        return None

    total_weight = sum(r.weight for r in counted)
    if total_weight <= 0:
        return None

    components: list[ScoreComponent] = []
    accumulated = 0.0
    for result in counted:
        normalised = result.weight / total_weight
        # A counted signal always has a rating; the fallback is for a rating
        # the config does not price, not for its absence.
        points = 0.0 if result.rating is None else config.rating_points.get(result.rating, 0.0)
        contribution = normalised * points
        accumulated += contribution
        components.append(
            ScoreComponent(
                signal_id=result.id,
                name=result.name,
                rating=str(result.rating),
                raw_weight=round(result.weight, 4),
                normalised_weight=round(normalised, 4),
                points=points,
                contribution=round(contribution * 100, 2),
            )
        )

    value = round(accumulated * 100, 1)
    total_signals = len(counted) + excluded
    low_confidence = total_signals > 0 and len(counted) < total_signals / 2
    return ReadinessScore(
        value=value,
        label=band_label(value),
        components=components,
        signals_counted=len(counted),
        signals_excluded=excluded,
        low_confidence=low_confidence,
        confidence_note=(
            f"Only {len(counted)} of {total_signals} signals could be measured for this "
            f"document, so this score rests on a small part of the picture. Read the "
            f"breakdown rather than the number."
            if low_confidence
            else None
        ),
        method=(
            f"{config.method}: each signal's rating scores "
            + ", ".join(f"{k}={v}" for k, v in config.rating_points.items())
            + f"; weights renormalised across the {count(len(counted), 'signal')} that produced "
            f"a rating for this document, then expressed out of 100."
        ),
    )
