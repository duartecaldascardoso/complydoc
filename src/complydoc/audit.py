"""Run the requested components over a target path and assemble one report.

The three components are independent. Asking for only the sensitive data scan
loads no tokenizer and computes no cost, and the report says plainly which
components were run so nobody reads a partial audit as a complete one.

With `jobs` above one the documents are spread over a process pool. That is a
wall-clock decision and nothing else: documents are analysed independently, so
the report comes out the same either way, and `tests/test_parallel.py` asserts
it. Because the pool uses spawn, code calling `run_audit` from a script must
guard its entry point with `if __name__ == "__main__":`, as with any use of
multiprocessing. The console entry point already does.
"""

from __future__ import annotations

import datetime as dt
import os
import platform
import time
from collections.abc import Callable, Iterator, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from multiprocessing import get_all_start_methods, get_context
from pathlib import Path
from typing import Any

from complydoc import __version__, offline
from complydoc.config.loader import check_staleness
from complydoc.config.schema import Config, ModelPricing
from complydoc.cost.estimator import estimate_document, folder_from_estimates, resolve_models
from complydoc.discovery import discover
from complydoc.ingest import ocr as ocr_module
from complydoc.ingest.base import Document, IngestOptions, LoaderError, SkipRecord
from complydoc.ingest.extractors.registry import DEFAULT_EXTRACTOR
from complydoc.ingest.registry import load_document
from complydoc.readiness.analyser import analyse
from complydoc.report.limitations import build_limitations
from complydoc.report.models import (
    SCHEMA_VERSION,
    AuditReport,
    DocumentReport,
    DocumentTiming,
    ExtractorReading,
    PageText,
    RunMetadata,
    build_aggregate,
)
from complydoc.report.preview import build_previews
from complydoc.sampling import sample_files
from complydoc.sensitive.scanner import scan

__all__ = ["COMPONENTS", "resolve_jobs", "run_audit"]

COMPONENTS = ("cost", "readiness", "sensitive")

_MAX_TEXT_CHARS = 20_000
"""Per page, so one enormous document cannot make the report unopenable."""


def _ner_available(config: Config) -> bool:
    """Whether the local NER model can be loaded, checked once per run."""
    from complydoc.sensitive.detectors.ner import model_available

    for category in config.sensitive.enabled_categories.values():
        if category.detector == "ner" and category.model is not None:
            ok, _ = model_available(category.model.name)
            return ok
    return False


def _relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root if root.is_dir() else root.parent))
    except ValueError:
        return str(path)


@dataclass(frozen=True, slots=True)
class _Work:
    """Everything analysing one document needs, and nothing that it does not.

    Kept picklable on purpose: with `--jobs` this is what crosses into each
    worker process. A `Document` never crosses back — it holds page rasters and
    is far larger than the report entry derived from it — so cost is estimated
    where the document already is, and only the finished entry is returned.
    """

    config: Config
    options: IngestOptions
    target: Path
    requested: tuple[str, ...]
    reveal: bool
    previews: bool
    page_images: bool
    extracted_text: bool
    models: tuple[ModelPricing, ...] | None
    today: dt.date


@dataclass(frozen=True, slots=True)
class _Outcome:
    entry: DocumentReport | None
    skipped: SkipRecord | None
    ocr_pages: int = 0
    ocr_seconds: float = 0.0


def _readings(document: Document) -> list[ExtractorReading]:
    """Each extractor's reading of the whole document, totalled over its pages.

    Order is preserved: the first is the one whose output the findings were
    built from, and the rest are there to be compared against it.
    """
    order: list[str] = []
    totals: dict[str, list[float]] = {}
    shape: dict[str, tuple[str, bool]] = {}

    for page in document.pages:
        for summary in page.extractions:
            if summary.extractor not in totals:
                order.append(summary.extractor)
                totals[summary.extractor] = [0.0, 0.0, 0.0, 0.0]
                shape[summary.extractor] = (summary.granularity, summary.reads_tables)
            row = totals[summary.extractor]
            row[0] += summary.characters
            row[1] += summary.coverage_pct
            row[2] += summary.seconds
            row[3] += 1

    readings: list[ExtractorReading] = []
    for name in order:
        characters, coverage, seconds, pages = totals[name]
        granularity, reads_tables = shape[name]
        readings.append(
            ExtractorReading(
                extractor=name,
                characters=int(characters),
                mean_coverage_pct=round(coverage / pages, 2) if pages else 0.0,
                seconds=round(seconds, 4),
                granularity=granularity,
                reads_tables=reads_tables,
            )
        )
    return readings


def _process(path: Path, work: _Work) -> _Outcome:
    """Read one document and produce its report entry. Never raises."""
    ocr_before = ocr_module.stats()
    read_started = time.perf_counter()
    try:
        document = load_document(path, work.options)
    except LoaderError as exc:
        return _Outcome(None, SkipRecord(path=path, reason="could not be parsed", detail=str(exc)))
    except Exception as exc:
        return _Outcome(
            None,
            SkipRecord(
                path=path,
                reason="unexpected error while reading",
                detail=f"{type(exc).__name__}: {exc}",
            ),
        )
    read_seconds = time.perf_counter() - read_started

    entry = DocumentReport(
        path=document.path,
        relative_path=_relative(document.path, work.target),
        sha256=document.sha256,
        format=document.format,
        page_count=document.page_count,
        page_count_known=document.page_count_known,
        load_warnings=list(document.load_warnings),
    )

    entry.extractions = _readings(document)

    analyse_started = time.perf_counter()
    if "readiness" in work.requested:
        entry.readiness = analyse(document, work.config.readiness)
    analyse_seconds = time.perf_counter() - analyse_started

    scan_started = time.perf_counter()
    if "sensitive" in work.requested:
        entry.sensitive = scan(document, work.config.sensitive, reveal=work.reveal)
    scan_seconds = time.perf_counter() - scan_started

    if work.models is not None:
        entry.cost = estimate_document(document, work.config.pricing, work.today, list(work.models))
    if work.previews:
        entry.previews = build_previews(
            document,
            entry.sensitive,
            page_images=work.page_images,
            categories=work.config.sensitive,
        )
    if work.extracted_text:
        entry.extracted_text = [
            PageText(
                number=page.number,
                source=page.text_source,
                characters=len(page.text),
                text=page.text[:_MAX_TEXT_CHARS],
                ocr_text=page.ocr_text[:_MAX_TEXT_CHARS],
                truncated=len(page.text) > _MAX_TEXT_CHARS,
            )
            for page in document.pages
        ]

    total_seconds = read_seconds + analyse_seconds + scan_seconds
    entry.timing = DocumentTiming(
        read_seconds=round(read_seconds, 3),
        analyse_seconds=round(analyse_seconds, 3),
        scan_seconds=round(scan_seconds, 3),
        total_seconds=round(total_seconds, 3),
        seconds_per_page=(
            round(total_seconds / document.page_count, 3) if document.page_count else None
        ),
    )
    ocr_after = ocr_module.stats()
    return _Outcome(entry, None, ocr_after[0] - ocr_before[0], ocr_after[1] - ocr_before[1])


_WORKER_WORK: _Work | None = None


def _pool_context() -> Any:
    """How to start the workers.

    Forkserver where it exists: the server process loads the tokenizer, the
    language model and the entity model once, and every worker forks from it
    with those already in memory. Under spawn each worker loads its own copy,
    which on a folder of small documents costs more than the work itself.

    Never a plain fork of this process. The OCR engine holds native threads, and
    forking a process that has them is a known way to hang a child; the
    forkserver is started before any of that exists.
    """
    if "forkserver" in get_all_start_methods():
        context = get_context("forkserver")
        context.set_forkserver_preload(["complydoc.warm"])
        return context
    return get_context("spawn")


def _worker_init(work: _Work) -> None:
    """Set up a worker process. The network guard is armed here too.

    A guard that only holds in the parent would be no guard at all, so every
    process that opens a document arms it before it opens anything.

    The native thread pools are pinned to one thread each. OCR otherwise spreads
    one page across every core, so without this the workers spend their time
    fighting each other for the same cores and the run gets slower rather than
    faster. It has to happen before the OCR engine is built, which is why it
    happens here.
    """
    global _WORKER_WORK
    for variable in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
        os.environ.setdefault(variable, "1")
    ocr_module.set_threads(1)
    offline.arm()
    _WORKER_WORK = work


def _worker(path: Path) -> _Outcome:
    assert _WORKER_WORK is not None
    return _process(path, _WORKER_WORK)


def _outcomes(files: list[Path], work: _Work, jobs: int) -> Iterator[_Outcome]:
    """Results in the order the files were discovered, serial or parallel."""
    if jobs <= 1 or len(files) < 2:
        for path in files:
            yield _process(path, work)
        return

    with ProcessPoolExecutor(
        max_workers=jobs,
        mp_context=_pool_context(),
        initializer=_worker_init,
        initargs=(work,),
    ) as pool:
        for outcome in pool.map(_worker, files, chunksize=1):
            ocr_module.add_stats(outcome.ocr_pages, outcome.ocr_seconds)
            yield outcome


_MIN_DOCUMENTS_PER_WORKER = 12
"""Below this, a worker costs more to start than the documents it would read.

Each one loads its own OCR engine, so a handful of documents spread over every
core spends its time on start-up. Measured on a folder of a hundred documents:
one process 13.6s, four 11.4s, eight 10.1s, and a folder of fifteen is quicker
in one process than in eleven.
"""


def resolve_jobs(jobs: int, files: int) -> int:
    """How many processes to use. 0 decides from the size of the folder."""
    if jobs == 0:
        jobs = min(os.cpu_count() or 1, files // _MIN_DOCUMENTS_PER_WORKER)
    return max(1, min(jobs, max(1, files)))


def run_audit(
    target: Path,
    config: Config,
    components: Sequence[str] = COMPONENTS,
    *,
    ocr: bool = False,
    reveal: bool = False,
    monthly_volume: int | None = None,
    resolution: str = "medium",
    select_models: Sequence[str] | None = None,
    recurse: bool = True,
    previews: bool = True,
    page_images: bool = False,
    extracted_text: bool = False,
    ocr_compare: bool = False,
    render_dpi: int = 150,
    password: str = "",
    extractor: str | None = None,
    compare_extractors: Sequence[str] = (),
    jobs: int = 1,
    sample: int | None = None,
    progress: Callable[[int, int, Path], None] | None = None,
) -> AuditReport:
    started = time.monotonic()
    started_at = dt.datetime.now().astimezone()
    requested = [c for c in COMPONENTS if c in set(components)]

    target = target.expanduser().resolve()
    files, skipped = discover(target, recurse=recurse)
    found = len(files)
    if sample is not None and sample < found:
        files = sample_files(files, sample)
    sampled = len(files) < found

    # Rasterising is only worth the memory when something will actually look at
    # the pixels — OCR, or the skew signal.
    wants_raster = ocr or page_images or ocr_compare or "readiness" in requested
    options = IngestOptions(
        ocr=ocr,
        render_dpi=render_dpi,
        extract_tables="readiness" in requested,
        render_all_pages=page_images or ocr_compare,
        ocr_compare=ocr_compare,
        max_render_pages=50 if (wants_raster or page_images) else 0,
        password=password,
        extractor=extractor or DEFAULT_EXTRACTOR,
        compare_extractors=tuple(compare_extractors),
    )
    chosen_extractor = extractor or DEFAULT_EXTRACTOR

    ocr_module.reset_stats()
    jobs = resolve_jobs(jobs, len(files))
    work = _Work(
        config=config,
        options=options,
        target=target,
        requested=tuple(requested),
        reveal=reveal,
        previews=previews,
        page_images=page_images,
        extracted_text=extracted_text,
        models=(
            tuple(resolve_models(config.pricing, select_models)) if "cost" in requested else None
        ),
        today=dt.date.today(),
    )

    documents: list[DocumentReport] = []
    for index, outcome in enumerate(_outcomes(files, work, jobs), start=1):
        if progress is not None:
            progress(index, len(files), files[index - 1])
        if outcome.skipped is not None:
            skipped.append(outcome.skipped)
        if outcome.entry is not None:
            documents.append(outcome.entry)

    folder_cost = None
    if "cost" in requested:
        folder_cost = folder_from_estimates(
            [e.cost for e in documents if e.cost is not None],
            config.pricing,
            headline_resolution=resolution,
            monthly_volume=monthly_volume,
        )

    finished_at = dt.datetime.now().astimezone()
    run = RunMetadata(
        tool_version=__version__,
        schema_version=SCHEMA_VERSION,
        started_at=started_at.isoformat(timespec="seconds"),
        finished_at=finished_at.isoformat(timespec="seconds"),
        duration_seconds=round(time.monotonic() - started, 3),
        target=str(target),
        components_run=requested,
        config_dir=config.source_dir,
        config_digest=config.digest,
        offline_guard=offline.guard_status(),
        reveal_used=reveal,
        page_images_used=page_images,
        extracted_text_used=extracted_text,
        ocr_compare_used=ocr_compare,
        ocr_requested=ocr,
        ocr_available=ocr_module.available(),
        ner_available=_ner_available(config) if "sensitive" in requested else False,
        python_version=platform.python_version(),
        monthly_volume=monthly_volume,
        jobs=jobs,
        sampled_from=found if sampled else None,
        sample_size=len(files) if sampled else None,
        password_used=bool(password),
        extractor=chosen_extractor,
        compare_extractors=list(compare_extractors),
    )

    staleness = check_staleness(config.pricing) if "cost" in requested else []
    report = AuditReport(
        run=run,
        documents=documents,
        skipped=skipped,
        cost=folder_cost,
        aggregate=build_aggregate(documents, skipped, folder_cost),
        staleness_warnings=[w.message for w in staleness],
        config_masking=config.sensitive.masking,
    )
    if "readiness" in requested and config.readiness.scoring.enabled:
        report.signal_weights = {
            sid: settings.weight
            for sid, settings in config.readiness.signals.items()
            if settings.enabled
        }
    report.limitations = build_limitations(run, documents, skipped, staleness, config)
    return report
