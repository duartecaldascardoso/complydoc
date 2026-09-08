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
from complydoc.difficulty.base import SignalResult

__all__ = ["DifficultyScore", "ScoreComponent", "compute_score"]


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
class DifficultyScore:
    value: float
    """0 (hardest) to 100 (easiest)."""
    label: str
    components: list[ScoreComponent]
    signals_counted: int
    signals_excluded: int
    method: str
    low_confidence: bool
    """True when most signals could not be measured, so the score rests on few lines."""
    confidence_note: str | None


def _label(value: float) -> str:
    if value >= 75:
        return "straightforward"
    if value >= 50:
        return "workable"
    if value >= 25:
        return "difficult"
    return "very difficult"


def compute_score(results: list[SignalResult], config: ScoringConfig) -> DifficultyScore | None:
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
        points = config.rating_points.get(result.rating, 0.0)  # type: ignore[arg-type]
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
    return DifficultyScore(
        value=value,
        label=_label(value),
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
            + f"; weights renormalised across the {len(counted)} signal(s) that produced "
            f"a rating for this document, then expressed out of 100."
        ),
    )
