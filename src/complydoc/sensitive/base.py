"""Types for the sensitive data scan.

Detectors return *spans*, never strings. Turning a span into something a human
can read is the exclusive job of `masking.render`, which is what makes it
structurally impossible for an unmasked value to reach a report by accident.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from complydoc.config.schema import CategoryConfig

__all__ = ["Detector", "DetectorContext", "Finding", "SensitiveMatch"]


@dataclass(frozen=True, slots=True)
class Finding:
    """A candidate span within one page's text. Carries no value."""

    start: int
    end: int
    confidence: float = 1.0
    context_term: str | None = None
    """Set when a generic pattern was only reported because of a nearby label."""


@dataclass(frozen=True, slots=True)
class DetectorContext:
    """Everything a detector is given about the category it is running for."""

    category_id: str
    config: CategoryConfig


@dataclass(frozen=True, slots=True)
class SensitiveMatch:
    """One reported hit. `revealed` is None unless --reveal was passed."""

    category: str
    label: str
    severity: str
    page: int
    line: int
    column: int
    length: int
    masked: str
    revealed: str | None = None
    confidence: float = 1.0
    validators_passed: list[str] = field(default_factory=list)
    context_term: str | None = None
    """The nearby label that justified reporting a generic pattern."""


@runtime_checkable
class Detector(Protocol):
    id: str

    def find(self, text: str, context: DetectorContext) -> list[Finding]: ...
