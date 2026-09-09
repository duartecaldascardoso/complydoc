"""RapidOCR on ONNX Runtime: the default.

Pip-installable, models bundled, no system binary to install, and no network
access at any point — which is why it is the one complydoc ships with.
"""

from __future__ import annotations

import atexit
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from complydoc.ingest.engines.base import Recognised
from complydoc.ingest.engines.registry import register

if TYPE_CHECKING:  # pragma: no cover - typing only
    from PIL.Image import Image

_IMPORT_ERROR: str | None = None
_threads: int | None = None


@lru_cache(maxsize=1)
def _pipeline() -> Any | None:
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
        built = RapidOCR(**options)
    except Exception as exc:  # pragma: no cover - engine init is environment-specific
        _IMPORT_ERROR = f"RapidOCR failed to initialise: {exc}"
        return None
    # Registered here, where the native threads are actually created, rather
    # than from a module that would have to import this one during interpreter
    # shutdown — by which point the import machinery may already be gone.
    atexit.register(release)
    return built


def release() -> None:
    """Drop the engine before the interpreter tears itself down.

    It holds native ONNX Runtime threads. Letting those be collected during
    interpreter shutdown occasionally aborts the process with a mutex error
    after the work has already finished — exit 134 on a run that had already
    succeeded.
    """
    _pipeline.cache_clear()


@register
class RapidOcrEngine:
    id = "rapidocr"
    name = "rapidocr-onnxruntime"

    def available(self) -> bool:
        return _pipeline() is not None

    def unavailable_reason(self) -> str | None:
        if self.available():
            return None
        return (
            "the optional OCR extra is not installed "
            f"(install with: uv sync --extra ocr)"
            f"{f' [{_IMPORT_ERROR}]' if _IMPORT_ERROR else ''}"
        )

    def set_threads(self, count: int | None) -> None:
        global _threads
        if count != _threads:
            _pipeline.cache_clear()
        _threads = count

    def read(self, image: Image) -> Recognised:
        pipeline = _pipeline()
        if pipeline is None:
            return Recognised("", None, 0)
        import numpy as np

        array = np.asarray(image.convert("RGB"))
        try:
            result, _ = pipeline(array)
        except Exception:  # pragma: no cover - a bad page should not kill the run
            return Recognised("", None, 0)
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
