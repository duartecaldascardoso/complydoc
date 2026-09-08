"""The report object, and the JSON schema it serialises to.

`SCHEMA_VERSION` is bumped whenever the JSON shape changes, so that runs stored
over time can be diffed with confidence about what a difference means.
"""

from __future__ import annotations

import datetime as dt
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from complydoc.config.schema import MaskingConfig
from complydoc.cost.estimator import DocumentCostEstimate, FolderCostEstimate
from complydoc.difficulty.analyser import DifficultyReport
from complydoc.difficulty.base import SignalStatus
from complydoc.ingest.base import DocumentFormat, SkipRecord
from complydoc.report.preview import PagePreview
from complydoc.sensitive.scanner import ScanResult

__all__ = [
    "SCHEMA_VERSION",
    "Aggregate",
    "AuditReport",
    "DocumentReport",
    "Limitation",
    "PageText",
    "RunMetadata",
]

SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class Limitation:
    """One thing this particular run did not or could not check."""

    area: str
    statement: str
    affected: list[str] = field(default_factory=list)
    severity: str = "info"
    """'info' or 'important'. Important means it could change a conclusion."""


@dataclass(frozen=True, slots=True)
class RunMetadata:
    tool_version: str
    schema_version: int
    started_at: str
    finished_at: str
    duration_seconds: float
    target: str
    components_run: list[str]
    config_dir: str
    config_digest: str
    offline_guard: str
    reveal_used: bool
    page_images_used: bool
    extracted_text_used: bool
    ocr_requested: bool
    ocr_available: bool
    ner_available: bool
    python_version: str
    monthly_volume: int | None


@dataclass(frozen=True, slots=True)
class PageText:
    """Exactly what was read off one page, for checking extraction quality."""

    number: int
    source: str
    characters: int
    text: str
    truncated: bool = False


@dataclass(slots=True)
class DocumentReport:
    path: Path
    relative_path: str
    sha256: str
    format: DocumentFormat
    page_count: int
    page_count_known: bool
    load_warnings: list[str] = field(default_factory=list)
    cost: DocumentCostEstimate | None = None
    difficulty: DifficultyReport | None = None
    sensitive: ScanResult | None = None
    previews: list[PagePreview] = field(default_factory=list)
    """Per-page wireframes. Geometry only — never document content."""
    extracted_text: list[PageText] = field(default_factory=list)
    """The text itself. Only populated with --extracted-text: it is the document."""


@dataclass(slots=True)
class Aggregate:
    """What a decision maker reads."""

    documents_audited: int
    documents_skipped: int
    pages_total: int
    pages_unreadable: int
    formats: dict[str, int] = field(default_factory=dict)

    total_text_path_usd: float | None = None
    total_vision_path_usd: float | None = None
    monthly_text_usd: float | None = None
    monthly_vision_usd: float | None = None
    annual_text_usd: float | None = None
    annual_vision_usd: float | None = None
    currency: str = "USD"

    signal_distribution: dict[str, dict[str, int]] = field(default_factory=dict)
    """signal id -> {good, fair, poor, not_applicable, error} counts across documents."""
    difficulty_bands: dict[str, int] = field(default_factory=dict)
    mean_difficulty_score: float | None = None

    sensitive_by_category: dict[str, int] = field(default_factory=dict)
    sensitive_by_severity: dict[str, int] = field(default_factory=dict)
    sensitive_total: int = 0
    documents_with_sensitive_data: int = 0
    categories_not_scanned: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class AuditReport:
    run: RunMetadata
    documents: list[DocumentReport] = field(default_factory=list)
    skipped: list[SkipRecord] = field(default_factory=list)
    cost: FolderCostEstimate | None = None
    aggregate: Aggregate | None = None
    limitations: list[Limitation] = field(default_factory=list)
    staleness_warnings: list[str] = field(default_factory=list)
    signal_weights: dict[str, float] = field(default_factory=dict)
    """Printed in the report whenever a score is shown, never hidden."""
    config_masking: MaskingConfig | None = None
    """Echoed so a reader can see exactly how much of a value was ever shown."""


def build_aggregate(
    documents: list[DocumentReport],
    skipped: list[SkipRecord],
    cost: FolderCostEstimate | None,
) -> Aggregate:
    formats: Counter[str] = Counter()
    pages = 0
    unreadable = 0
    signal_distribution: dict[str, dict[str, int]] = {}
    scores: list[float] = []
    bands: Counter[str] = Counter()
    by_category: Counter[str] = Counter()
    by_severity: Counter[str] = Counter()
    not_scanned: dict[str, str] = {}
    with_sensitive = 0

    for document in documents:
        formats[document.format.value] += 1
        pages += document.page_count

        if document.difficulty is not None:
            for signal in document.difficulty.signals:
                bucket = signal_distribution.setdefault(
                    signal.id,
                    {"good": 0, "fair": 0, "poor": 0, "not_applicable": 0, "error": 0},
                )
                if signal.status is SignalStatus.ERROR:
                    bucket["error"] += 1
                elif signal.status is SignalStatus.NOT_APPLICABLE:
                    bucket["not_applicable"] += 1
                elif signal.rating:
                    bucket[signal.rating] += 1
            if document.difficulty.score is not None:
                scores.append(document.difficulty.score.value)
                bands[document.difficulty.score.label] += 1

        if document.sensitive is not None:
            unreadable += len(document.sensitive.unreadable_pages)
            by_category.update(document.sensitive.counts_by_category)
            by_severity.update(document.sensitive.counts_by_severity)
            if document.sensitive.total:
                with_sensitive += 1
            for entry in document.sensitive.unscanned_categories:
                not_scanned.setdefault(entry.category, entry.reason)

    aggregate = Aggregate(
        documents_audited=len(documents),
        documents_skipped=len(skipped),
        pages_total=pages,
        pages_unreadable=unreadable,
        formats=dict(formats),
        signal_distribution=signal_distribution,
        difficulty_bands=dict(bands),
        mean_difficulty_score=round(sum(scores) / len(scores), 1) if scores else None,
        sensitive_by_category=dict(by_category),
        sensitive_by_severity=dict(by_severity),
        sensitive_total=int(sum(by_category.values())),
        documents_with_sensitive_data=with_sensitive,
        categories_not_scanned=not_scanned,
    )

    if cost is not None:
        resolution = cost.headline_resolution
        aggregate.currency = cost.currency
        aggregate.total_text_path_usd = cost.total_text_path_usd()
        aggregate.total_vision_path_usd = cost.total_vision_path_usd(resolution)
        if cost.volume is not None:
            aggregate.monthly_text_usd = cost.volume.monthly_text_usd
            aggregate.monthly_vision_usd = cost.volume.monthly_vision_usd
            aggregate.annual_text_usd = cost.volume.annual_text_usd
            aggregate.annual_vision_usd = cost.volume.annual_vision_usd

    return aggregate


def to_jsonable(value: Any) -> Any:
    """Convert the report tree into something json.dump can write."""
    import dataclasses
    import enum

    from pydantic import BaseModel

    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: to_jsonable(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dt.date | dt.datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [to_jsonable(v) for v in value]
    return value
