"""Types for the sensitive data scan.

Detectors return *spans*, never strings. Turning a span into something a human
can read is the exclusive job of `masking.render`, which is what makes it
structurally impossible for an unmasked value to reach a report by accident.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final, Literal, Protocol, runtime_checkable

from complydoc.config.schema import CategoryConfig

__all__ = [
    "EVIDENCE_ORDER",
    "SEVERITY_WEIGHT",
    "Detector",
    "DetectorContext",
    "Evidence",
    "Finding",
    "SensitiveMatch",
    "evidence_of",
]

Evidence = Literal["confirmed", "corroborated", "pattern", "model"]
"""How strong the case for a finding is.

A number would suggest a precision nobody has. These four say what was actually
established, and they sort:

`confirmed`
    A checksum passed. A card number that satisfies Luhn is a card number.
`corroborated`
    The shape matched and a label sits next to it — "IBAN:", "Sort code".
`pattern`
    The shape matched and nothing else confirms it. Nine digits in a row are
    nine digits in a row.
`model`
    A statistical model named it. No checksum exists for a person's name, so
    this is the strongest evidence available for such a category and the
    weakest evidence in the list. Expect both misses and false positives.
"""


@dataclass(frozen=True, slots=True)
class Finding:
    """A candidate span within one page's text. Carries no value."""

    start: int
    end: int
    confidence: float | None = 1.0
    """The detector's own score, or None where the detector has none to give."""
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
    evidence: Evidence = "pattern"
    """How strong the case for this finding is — see `Evidence`."""
    confidence: float | None = 1.0
    """The detector's own score, where the detector produces one.

    None for a detector that produces none. A statistical model that cannot
    report a score has not scored 1.0, and recording it as such put a guess and
    a passed checksum side by side as equals.
    """
    validators_passed: list[str] = field(default_factory=list)
    context_term: str | None = None
    """The nearby label that justified reporting a generic pattern."""


SEVERITY_WEIGHT: Final[dict[str, int]] = {"high": 3, "medium": 2, "low": 1}
"""How the three severities compare, for sorting and for scoring exposure.

One table, because it was two: a fourth severity added to the config would
otherwise have to be remembered in the report as well as in the score. What to
do with a severity that is not in it differs by caller — last when sorting, not
free when scoring — so each says so where it asks.
"""

EVIDENCE_ORDER: Final = ("confirmed", "corroborated", "pattern", "model")
"""Strongest first. The order the security page sorts by within a severity."""


def evidence_of(detector: str, validators_passed: list[str], context_term: str | None) -> Evidence:
    """Which tier a finding earned, from what actually happened to it.

    Derived rather than declared, so a detector cannot claim more for its
    findings than the checks they survived.
    """
    if validators_passed:
        return "confirmed"
    if context_term:
        return "corroborated"
    if detector == "ner":
        return "model"
    return "pattern"


@runtime_checkable
class Detector(Protocol):
    id: str

    def find(self, text: str, context: DetectorContext) -> list[Finding]: ...
