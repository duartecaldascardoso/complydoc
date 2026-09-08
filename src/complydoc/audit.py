"""Run the requested components over a target path and assemble one report.

The three components are independent. Asking for only the sensitive data scan
loads no tokenizer and computes no cost, and the report says plainly which
components were run so nobody reads a partial audit as a complete one.
"""

from __future__ import annotations

import datetime as dt
import platform
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from complydoc import __version__, offline
from complydoc.config.loader import check_staleness
from complydoc.config.schema import Config
from complydoc.cost.estimator import estimate_folder
from complydoc.difficulty.analyser import analyse
from complydoc.discovery import discover
from complydoc.ingest import ocr as ocr_module
from complydoc.ingest.base import Document, IngestOptions, LoaderError, SkipRecord
from complydoc.ingest.registry import load_document
from complydoc.report.limitations import build_limitations
from complydoc.report.models import (
    SCHEMA_VERSION,
    AuditReport,
    DocumentReport,
    RunMetadata,
    build_aggregate,
)
from complydoc.report.preview import build_previews
from complydoc.sensitive.scanner import scan

__all__ = ["COMPONENTS", "run_audit"]

COMPONENTS = ("cost", "difficulty", "sensitive")


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
    render_dpi: int = 150,
    progress: Callable[[int, int, Path], None] | None = None,
) -> AuditReport:
    started = time.monotonic()
    started_at = dt.datetime.now().astimezone()
    requested = [c for c in COMPONENTS if c in set(components)]

    target = target.expanduser().resolve()
    files, skipped = discover(target, recurse=recurse)

    # Rasterising is only worth the memory when something will actually look at
    # the pixels — OCR, or the skew signal.
    wants_raster = ocr or "difficulty" in requested
    options = IngestOptions(
        ocr=ocr,
        render_dpi=render_dpi,
        extract_tables="difficulty" in requested,
        max_render_pages=50 if wants_raster else 0,
    )

    documents: list[DocumentReport] = []
    loaded: list[Document] = []

    for index, path in enumerate(files, start=1):
        if progress is not None:
            progress(index, len(files), path)
        try:
            document = load_document(path, options)
        except LoaderError as exc:
            skipped.append(SkipRecord(path=path, reason="could not be parsed", detail=str(exc)))
            continue
        except Exception as exc:
            skipped.append(
                SkipRecord(
                    path=path,
                    reason="unexpected error while reading",
                    detail=f"{type(exc).__name__}: {exc}",
                )
            )
            continue

        loaded.append(document)
        entry = DocumentReport(
            path=document.path,
            relative_path=_relative(document.path, target),
            sha256=document.sha256,
            format=document.format,
            page_count=document.page_count,
            page_count_known=document.page_count_known,
            load_warnings=list(document.load_warnings),
        )
        if "difficulty" in requested:
            entry.difficulty = analyse(document, config.difficulty)
        if "sensitive" in requested:
            entry.sensitive = scan(document, config.sensitive, reveal=reveal)
        if previews:
            entry.previews = build_previews(document, entry.sensitive)
        documents.append(entry)

    folder_cost = None
    if "cost" in requested:
        folder_cost = estimate_folder(
            loaded,
            config.pricing,
            headline_resolution=resolution,
            monthly_volume=monthly_volume,
            select_models=select_models,
        )
        for entry, estimate in zip(documents, folder_cost.documents, strict=True):
            entry.cost = estimate

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
        ocr_requested=ocr,
        ocr_available=ocr_module.available(),
        ner_available=_ner_available(config) if "sensitive" in requested else False,
        python_version=platform.python_version(),
        monthly_volume=monthly_volume,
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
    if "difficulty" in requested and config.difficulty.scoring.enabled:
        report.signal_weights = {
            sid: settings.weight
            for sid, settings in config.difficulty.signals.items()
            if settings.enabled
        }
    report.limitations = build_limitations(run, documents, skipped, staleness, config)
    return report
