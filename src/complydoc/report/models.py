"""The report object, and the JSON schema it serialises to.

`SCHEMA_VERSION` is bumped whenever the JSON shape changes, so that runs stored
over time can be diffed with confidence about what a difference means.

Version 2 renamed the difficulty component to readiness. A high score always
meant a document that was easy to process, which read backwards under a name
that promised the opposite.
"""

from __future__ import annotations

import datetime as dt
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from complydoc.config.schema import MaskingConfig
from complydoc.cost.estimator import DocumentCostEstimate, FolderCostEstimate
from complydoc.ingest import ocr as ocr_module
from complydoc.ingest.base import DocumentFormat, SkipRecord
from complydoc.readiness.analyser import ReadinessReport
from complydoc.readiness.base import SignalStatus
from complydoc.report.preview import PagePreview
from complydoc.sensitive.scanner import ScanResult

__all__ = [
    "SCHEMA_VERSION",
    "Aggregate",
    "AuditReport",
    "DocumentReport",
    "DocumentTiming",
    "ExtractorReading",
    "Limitation",
    "PageText",
    "RunMetadata",
]

SCHEMA_VERSION = 2


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
    ocr_compare_used: bool
    ocr_requested: bool
    ocr_available: bool
    ner_available: bool
    python_version: str
    monthly_volume: int | None
    extractor: str = "pdfplumber"
    """Which extractor's reading the findings were built from."""
    compare_extractors: list[str] = field(default_factory=list)
    compare_engines: list[str] = field(default_factory=list)
    jobs: int = 1
    """Worker processes used. More than one changes nothing about the findings."""
    sampled_from: int | None = None
    """Documents found, when --sample meant only some of them were opened."""
    sample_size: int | None = None
    """Documents the sample selected. Fewer may appear if one failed to parse."""
    password_used: bool = False


@dataclass(frozen=True, slots=True)
class DocumentTiming:
    """Wall clock spent on one document, measured rather than modelled."""

    read_seconds: float
    analyse_seconds: float
    scan_seconds: float
    total_seconds: float
    seconds_per_page: float | None


@dataclass(frozen=True, slots=True)
class PageText:
    """Exactly what was read off one page, for checking extraction quality."""

    number: int
    source: str
    characters: int
    text: str
    ocr_text: str = ""
    truncated: bool = False
    readings: dict[str, str] = field(default_factory=dict)
    """What each reader compared on this run made of the page, by name."""


_SIMILAR_ENOUGH = 0.95
"""Below this, two readings of a page are telling different stories.

Line endings and stray whitespace put honest extractors at about 0.99 of each
other; a scrambled two-column page measures around 0.1.
"""


@dataclass(frozen=True, slots=True)
class ExtractorReading:
    """What one extractor made of one document, totalled over its pages."""

    extractor: str
    characters: int
    mean_coverage_pct: float | None
    """None when the reader returns no geometry to measure coverage from."""
    seconds: float
    granularity: str
    reads_tables: bool
    similarity: float = 1.0
    """How closely this reading matched the one kept, compared in order."""

    @property
    def read_nothing(self) -> bool:
        return self.characters == 0


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
    readiness: ReadinessReport | None = None
    sensitive: ScanResult | None = None
    previews: list[PagePreview] = field(default_factory=list)
    """Per-page wireframes. Geometry only — never document content."""
    timing: DocumentTiming | None = None
    extracted_text: list[PageText] = field(default_factory=list)
    """The text itself. Only populated with --extracted-text: it is the document."""
    extractions: list[ExtractorReading] = field(default_factory=list)
    """One per extractor the run was asked for. The first is the one kept."""

    @property
    def extractors_disagree(self) -> bool:
        """Whether the extractors read this document differently enough to say so.

        Measured against the one whose output was kept. A tenth of the text is
        the line: below that the difference is line endings and whitespace, and
        reporting it would be noise on every document.
        """
        return self.disagreement is not None

    @property
    def disagreement(self) -> str | None:
        """What the extractors disagreed about, in the words a reader needs.

        "They differ" sends someone to compare two thousand characters by eye.
        Naming the kind of difference says where to look.
        """
        if len(self.extractions) < 2:
            return None
        kept = self.extractions[0]
        for other in self.extractions[1:]:
            if kept.read_nothing != other.read_nothing:
                return "one of them read nothing"
            highest = max(kept.characters, other.characters, 1)
            if abs(kept.characters - other.characters) / highest > 0.10:
                return "they read different amounts"
            # Counting characters is not enough. Two extractors can return the
            # same characters in a different order — one reading straight
            # across a two-column page and scrambling every sentence — and a
            # count says they agreed.
            if other.similarity < _SIMILAR_ENOUGH:
                return "same text, different order"
        return None


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
    readiness_bands: dict[str, int] = field(default_factory=dict)
    mean_readiness_score: float | None = None

    sensitive_by_category: dict[str, int] = field(default_factory=dict)
    sensitive_by_severity: dict[str, int] = field(default_factory=dict)
    sensitive_total: int = 0
    documents_with_sensitive_data: int = 0
    categories_not_scanned: dict[str, str] = field(default_factory=dict)

    total_seconds: float = 0.0
    """Wall clock for the whole run, measured on the machine that ran it."""
    seconds_per_document: float | None = None
    seconds_per_page: float | None = None
    ocr_pages: int = 0
    ocr_seconds: float = 0.0
    ocr_pages_per_second: float | None = None
    hours_per_1000_documents: float | None = None
    read_seconds: float = 0.0
    """Opening the file and pulling text, words and geometry out of it."""
    analyse_seconds: float = 0.0
    """Measuring the readiness signals."""
    scan_seconds: float = 0.0
    """Searching the text for identifiers."""
    projected_seconds: dict[str, float] = field(default_factory=dict)
    """Wall clock for a backlog of a given size, at the rate this run measured.

    Extrapolated from documents like these ones. A folder of longer or heavier
    scans takes longer, and this says nothing about time spent on the model.
    """


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

        if document.readiness is not None:
            for signal in document.readiness.signals:
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
            if document.readiness.score is not None:
                scores.append(document.readiness.score.value)
                bands[document.readiness.score.label] += 1

        if document.sensitive is not None:
            unreadable += len(document.sensitive.unreadable_pages)
            by_category.update(document.sensitive.counts_by_category)
            by_severity.update(document.sensitive.counts_by_severity)
            if document.sensitive.total:
                with_sensitive += 1
            for entry in document.sensitive.unscanned_categories:
                not_scanned.setdefault(entry.category, entry.reason)

    timings = [d.timing for d in documents if d.timing]
    measured_seconds = sum(t.total_seconds for t in timings)
    ocr_pages, ocr_seconds = ocr_module.stats()

    aggregate = Aggregate(
        documents_audited=len(documents),
        documents_skipped=len(skipped),
        pages_total=pages,
        pages_unreadable=unreadable,
        formats=dict(formats),
        signal_distribution=signal_distribution,
        readiness_bands=dict(bands),
        mean_readiness_score=round(sum(scores) / len(scores), 1) if scores else None,
        sensitive_by_category=dict(by_category),
        sensitive_by_severity=dict(by_severity),
        sensitive_total=int(sum(by_category.values())),
        documents_with_sensitive_data=with_sensitive,
        categories_not_scanned=not_scanned,
        total_seconds=round(measured_seconds, 3),
        seconds_per_document=(round(measured_seconds / len(timings), 3) if timings else None),
        seconds_per_page=round(measured_seconds / pages, 3) if pages else None,
        ocr_pages=ocr_pages,
        ocr_seconds=ocr_seconds,
        ocr_pages_per_second=(round(ocr_pages / ocr_seconds, 2) if ocr_seconds > 0 else None),
        hours_per_1000_documents=(
            round(measured_seconds / len(timings) * 1000 / 3600, 2) if timings else None
        ),
        read_seconds=round(sum(t.read_seconds for t in timings), 3),
        analyse_seconds=round(sum(t.analyse_seconds for t in timings), 3),
        scan_seconds=round(sum(t.scan_seconds for t in timings), 3),
        projected_seconds=(
            {
                str(size): round(measured_seconds / len(timings) * size, 1)
                for size in (100, 1_000, 10_000, 100_000)
            }
            if timings
            else {}
        ),
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
