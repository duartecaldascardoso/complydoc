"""Optional local OCR.

OCR is an optional extra (`uv sync --extra ocr`) because it is a large download
and a diagnostic run is still useful without it. When it is missing, every page
that could not be read is named individually in the report's limitations rather
than being quietly counted as containing nothing — a sensitive data scan that
silently returns zero on a scanned bank statement is worse than one that says it
could not look.

The engine itself lives in `engines/`, chosen by name. This module is what the
rest of complydoc talks to: which engine is selected, how much work it did, and
how long it took.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from complydoc.ingest.engines.base import Engine, Recognised
from complydoc.ingest.engines.registry import DEFAULT_ENGINE, engine_by_id

if TYPE_CHECKING:  # pragma: no cover - typing only
    from PIL.Image import Image

__all__ = [
    "Recognised",
    "add_stats",
    "available",
    "engine_name",
    "reset_stats",
    "run",
    "select",
    "set_threads",
    "stats",
    "unavailable_reason",
]

# OCR dominates the wall clock on a folder of scans, and how fast it runs is a
# property of this machine rather than something worth guessing at. It is
# measured here so the report can quote a rate it actually observed.
_pages = 0
_seconds = 0.0
_selected = DEFAULT_ENGINE


def select(engine_id: str | None) -> None:
    """Choose the engine. Unknown names fall back to the default rather than failing."""
    global _selected
    if engine_id and engine_by_id(engine_id) is not None:
        _selected = engine_id


def _engine() -> Engine | None:
    return engine_by_id(_selected)


def available() -> bool:
    engine = _engine()
    return engine is not None and engine.available()


def unavailable_reason() -> str | None:
    engine = _engine()
    if engine is None:
        return f"no OCR engine called {_selected!r} is registered"
    reason: str | None = engine.unavailable_reason()
    return reason


def engine_name() -> str:
    engine = _engine()
    return engine.name if engine is not None else _selected


def set_threads(count: int | None) -> None:
    """Limit the engine's own threading. Must be called before the first page.

    The engine spreads a single page across every core by default, which is the
    right thing for one process and the wrong thing for several: with `--jobs`
    the workers end up competing for the same cores and the run gets slower. A
    worker pins itself to one thread and lets the process pool do the spreading.
    """
    engine = _engine()
    if engine is not None:
        engine.set_threads(count)


def reset_stats() -> None:
    """Start counting again. Called once at the top of a run."""
    global _pages, _seconds
    _pages, _seconds = 0, 0.0


def add_stats(pages: int, seconds: float) -> None:
    """Fold in counts measured in another process.

    With `--jobs` the OCR happens in worker processes, each with its own copy of
    these counters. The workers hand their totals back so the report can still
    quote a rate for the run as a whole.
    """
    global _pages, _seconds
    _pages += pages
    _seconds += seconds


def stats() -> tuple[int, float]:
    """Pages read and seconds spent reading them, in this process."""
    return _pages, round(_seconds, 3)


def run(image: Image) -> Recognised:
    """Read one page image, with the engine's own confidence in what it read."""
    global _pages, _seconds

    engine = _engine()
    if engine is None or not engine.available():
        return Recognised("", None, 0)

    started = time.perf_counter()
    try:
        read: Recognised = engine.read(image)
        return read
    finally:
        _seconds += time.perf_counter() - started
        _pages += 1
