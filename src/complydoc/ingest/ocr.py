"""Optional local OCR.

OCR is an optional extra (`uv sync --extra ocr`) because it is a large download
and a diagnostic run is still useful without it. When it is missing, every page
that could not be read is named individually in the report's limitations rather
than being quietly counted as containing nothing — a sensitive data scan that
silently returns zero on a scanned bank statement is worse than one that says it
could not look.

The engine is RapidOCR on ONNX Runtime: pip-installable, models bundled, no
system binary to install, and no network access at any point.
"""

from __future__ import annotations

import atexit
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from PIL.Image import Image

__all__ = [
    "Recognised",
    "add_stats",
    "available",
    "engine_name",
    "reset_stats",
    "run",
    "set_threads",
    "stats",
    "unavailable_reason",
]

_IMPORT_ERROR: str | None = None

_threads: int | None = None
"""Native threads the engine may use per page. None leaves it to the engine."""


def set_threads(count: int | None) -> None:
    """Limit the engine's own threading. Must be called before the first page.

    The engine spreads a single page across every core by default, which is the
    right thing for one process and the wrong thing for several: with `--jobs`
    the workers end up competing for the same cores and the run gets slower. A
    worker pins itself to one thread and lets the process pool do the spreading.
    """
    global _threads
    if count != _threads:
        _engine.cache_clear()
    _threads = count


# OCR dominates the wall clock on a folder of scans, and how fast it runs is a
# property of this machine rather than something worth guessing at. It is
# measured here so the report can quote a rate it actually observed.
_pages = 0
_seconds = 0.0


@dataclass(frozen=True, slots=True)
class Recognised:
    """What OCR read, and how sure it was.

    The engine reports a confidence for every box it recognises and we used to
    throw them away, which left OCR text asserted with exactly the same
    authority as a native text layer. It does not deserve that.
    """

    text: str
    confidence: float | None
    boxes: int


@lru_cache(maxsize=1)
def _engine() -> Any | None:
    global _IMPORT_ERROR
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError as exc:
        _IMPORT_ERROR = str(exc)
        return None
    options = (
        {"intra_op_num_threads": _threads, "inter_op_num_threads": _threads}
        if _threads is not None
        else {}
    )
    try:
        return RapidOCR(**options)
    except Exception as exc:  # pragma: no cover - engine init is environment-specific
        _IMPORT_ERROR = f"RapidOCR failed to initialise: {exc}"
        return None


def _release() -> None:
    """Drop the engine before the interpreter tears itself down.

    RapidOCR holds native ONNX Runtime threads. Letting those be collected during
    interpreter shutdown occasionally aborts the process with a mutex error after
    the work has already finished, which turns a green test run into exit 134.
    Releasing early avoids the race.
    """
    _engine.cache_clear()


atexit.register(_release)


def available() -> bool:
    return _engine() is not None


def unavailable_reason() -> str | None:
    if available():
        return None
    _engine()
    return (
        "the optional OCR extra is not installed "
        f"(install with: uv sync --extra ocr){f' [{_IMPORT_ERROR}]' if _IMPORT_ERROR else ''}"
    )


def engine_name() -> str:
    return "rapidocr-onnxruntime"


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
    if engine is None:
        return Recognised("", None, 0)
    import numpy as np

    array = np.asarray(image.convert("RGB"))
    started = time.perf_counter()
    try:
        result, _ = engine(array)
    except Exception:  # pragma: no cover - a bad page should not kill the run
        return Recognised("", None, 0)
    finally:
        _seconds += time.perf_counter() - started
        _pages += 1
    if not result:
        return Recognised("", None, 0)

    lines = [str(item[1]) for item in result if len(item) > 1]
    scores = [
        float(item[2]) for item in result if len(item) > 2 and isinstance(item[2], int | float)
    ]
    return Recognised(
        text="\n".join(lines),
        confidence=round(sum(scores) / len(scores), 3) if scores else None,
        boxes=len(lines),
    )
