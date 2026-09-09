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
from functools import lru_cache
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from PIL.Image import Image

__all__ = ["available", "engine_name", "reset_stats", "run", "stats", "unavailable_reason"]

_IMPORT_ERROR: str | None = None

# OCR dominates the wall clock on a folder of scans, and how fast it runs is a
# property of this machine rather than something worth guessing at. It is
# measured here so the report can quote a rate it actually observed.
_pages = 0
_seconds = 0.0


@lru_cache(maxsize=1)
def _engine() -> Any | None:
    global _IMPORT_ERROR
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError as exc:
        _IMPORT_ERROR = str(exc)
        return None
    try:
        return RapidOCR()
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


def stats() -> tuple[int, float]:
    """Pages read and seconds spent reading them, in this process."""
    return _pages, round(_seconds, 3)


def run(image: Image) -> str:
    """Return recognised text for one page image, or an empty string."""
    global _pages, _seconds

    engine = _engine()
    if engine is None:
        return ""
    import numpy as np

    array = np.asarray(image.convert("RGB"))
    started = time.perf_counter()
    try:
        result, _ = engine(array)
    except Exception:  # pragma: no cover - a bad page should not kill the run
        return ""
    finally:
        _seconds += time.perf_counter() - started
        _pages += 1
    if not result:
        return ""
    lines = [str(item[1]) for item in result if len(item) > 1]
    return "\n".join(lines)
