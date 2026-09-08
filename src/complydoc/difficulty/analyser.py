"""Component 2: run every registered signal against one document."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from complydoc.config.schema import DifficultyConfig, SignalConfig
from complydoc.difficulty.base import Measurement, Signal, SignalResult, SignalStatus
from complydoc.difficulty.registry import all_signals
from complydoc.difficulty.scoring import DifficultyScore, compute_score
from complydoc.ingest.base import Document, DocumentFormat

__all__ = ["DifficultyReport", "analyse"]


@dataclass(slots=True)
class DifficultyReport:
    path: Path
    format: DocumentFormat
    signals: list[SignalResult] = field(default_factory=list)
    score: DifficultyScore | None = None
    unconfigured_signals: list[str] = field(default_factory=list)
    """Registered signals with no entry in difficulty.yaml. Measured but unrated."""

    @property
    def not_applicable(self) -> list[SignalResult]:
        return [s for s in self.signals if s.status is SignalStatus.NOT_APPLICABLE]

    @property
    def errored(self) -> list[SignalResult]:
        return [s for s in self.signals if s.status is SignalStatus.ERROR]

    def by_rating(self, rating: str) -> list[SignalResult]:
        return [s for s in self.signals if s.rating == rating]


def _article(word: str) -> str:
    """ "a" or "an", so the generated reasons read like English."""
    return "an" if word[:1].lower() in "aeiou" else "a"


def _result(
    signal: Signal,
    settings: SignalConfig | None,
    status: SignalStatus,
    measurement: Measurement,
    reason: str | None = None,
) -> SignalResult:
    rating = None
    if status is SignalStatus.MEASURED and settings is not None:
        rating = settings.rate(measurement.value)
    return SignalResult(
        id=signal.id,
        name=signal.name,
        status=status,
        value=measurement.value,
        display=measurement.display or "-",
        unit=signal.unit,
        why=(settings.why if settings and settings.why else signal.why),
        rating=rating,
        weight=settings.weight if settings else 0.0,
        detail=measurement.detail,
        reason=reason or measurement.not_applicable_reason,
    )


def analyse(document: Document, config: DifficultyConfig) -> DifficultyReport:
    report = DifficultyReport(path=document.path, format=document.format)

    for signal in sorted(all_signals(), key=lambda s: s.id):
        settings = config.for_signal(signal.id)
        if settings is None:
            report.unconfigured_signals.append(signal.id)
        elif not settings.enabled:
            continue

        if document.format not in signal.applies_to:
            report.signals.append(
                _result(
                    signal,
                    settings,
                    SignalStatus.NOT_APPLICABLE,
                    Measurement.na(
                        f"this signal is only meaningful for "
                        f"{', '.join(sorted(f.value for f in signal.applies_to))} files, "
                        f"and this is {_article(document.format.value)} "
                        f"{document.format.value} file"
                    ),
                )
            )
            continue

        try:
            measurement = signal.measure(document)
        except Exception as exc:
            report.signals.append(
                _result(
                    signal,
                    settings,
                    SignalStatus.ERROR,
                    Measurement(display="could not be measured"),
                    reason=f"{type(exc).__name__}: {exc}",
                )
            )
            continue

        status = (
            SignalStatus.NOT_APPLICABLE
            if measurement.not_applicable_reason
            else SignalStatus.MEASURED
        )
        report.signals.append(_result(signal, settings, status, measurement))

    report.score = compute_score(report.signals, config.scoring)
    return report
