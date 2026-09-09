"""What a readiness signal is.

A signal measures one specific, nameable property of a document and explains in
one sentence why that property matters for extraction. It does not produce a
score and it does not know about any other signal. That is deliberate: the
report is a table of independent lines, and a reader must be able to reject any
one line without rejecting the rest.

A signal that cannot measure its property for a given document returns
`Measurement.na(reason)`. That is not a zero and it is not a failure — it is
recorded as not applicable and the reason is carried into the report's
limitations section.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from complydoc.config.schema import Rating
from complydoc.ingest.base import Document, DocumentFormat

__all__ = [
    "ALL_FORMATS",
    "Measurement",
    "Signal",
    "SignalResult",
    "SignalStatus",
]

ALL_FORMATS = frozenset(DocumentFormat)


class SignalStatus(StrEnum):
    MEASURED = "measured"
    NOT_APPLICABLE = "not_applicable"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class Measurement:
    """What a signal returns."""

    value: float | int | bool | None = None
    display: str = ""
    detail: dict[str, Any] = field(default_factory=dict)
    """Supporting numbers, shown under the row so the value can be checked."""
    not_applicable_reason: str | None = None

    @classmethod
    def na(cls, reason: str) -> Measurement:
        return cls(value=None, display="not applicable", not_applicable_reason=reason)


@dataclass(frozen=True, slots=True)
class SignalResult:
    """One row of the readiness table."""

    id: str
    name: str
    status: SignalStatus
    value: float | int | bool | None
    display: str
    unit: str | None
    why: str
    rating: Rating | None
    weight: float
    detail: dict[str, Any]
    reason: str | None
    """Why the signal is not applicable, or what went wrong."""

    @property
    def counts_towards_score(self) -> bool:
        return self.status is SignalStatus.MEASURED and self.rating is not None


@runtime_checkable
class Signal(Protocol):
    """Implemented by every module under `readiness/signals/`."""

    id: str
    name: str
    unit: str | None
    why: str
    """The default plain-English sentence. readiness.yaml can override it."""
    applies_to: frozenset[DocumentFormat]

    def measure(self, document: Document) -> Measurement: ...
