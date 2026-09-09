"""What an OCR engine is asked for, and what it hands back.

Unlike the PDF extractors, which agree on the text of a page to within a per
cent, OCR engines genuinely disagree: they read different words, and they differ
about how sure they are. That makes a comparison worth running.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:  # pragma: no cover - typing only
    from PIL.Image import Image

__all__ = ["Engine", "Recognised"]


@dataclass(frozen=True, slots=True)
class Recognised:
    """What an engine read, and how sure it was.

    An engine reports a confidence for every box it recognises. Throwing those
    away would leave OCR text asserted with the same authority as a native text
    layer, which it has not earned.
    """

    text: str
    confidence: float | None
    boxes: int


@runtime_checkable
class Engine(Protocol):
    id: str
    name: str

    def available(self) -> bool: ...

    def unavailable_reason(self) -> str | None: ...

    def set_threads(self, count: int | None) -> None:
        """Limit the engine's own threading, before it reads its first page."""
        ...

    def read(self, image: Image) -> Recognised: ...
