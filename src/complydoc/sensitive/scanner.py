"""Component 3: find personal and financial identifiers, and report them masked.

The scan reports counts and locations. Values are masked unless `--reveal` was
passed, and categories under `masking.never_reveal` stay masked even then.

Pages with no readable text are recorded by number rather than treated as
containing nothing. A scanned bank statement that nobody could read is not a
clean bank statement, and a report that implies otherwise is dangerous.
"""

from __future__ import annotations

from bisect import bisect_right
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from complydoc.config.schema import CategoryConfig, SensitiveConfig
from complydoc.ingest.base import Document
from complydoc.sensitive.base import (
    DetectorContext,
    Finding,
    SensitiveMatch,
    evidence_of,
)
from complydoc.sensitive.masking import render
from complydoc.sensitive.registry import DetectorUnavailableError, detector_by_id
from complydoc.sensitive.validators import validate

__all__ = ["ScanResult", "UnscannedCategory", "scan"]

# Categories where one run of characters can only be one identifier. Within this
# group overlapping matches are resolved longest-first, so a phone-number pattern
# does not also report the middle of a card number. Categories outside the group
# are independent: a postcode inside a street address is two real findings.
_EXCLUSIVE_GROUP = frozenset(
    {
        "ni_number",
        "sort_code",
        "bank_account_number",
        "iban",
        "card_number",
        "phone_number",
        "date_of_birth",
        "vat_number",
        "utr",
    }
)


@dataclass(frozen=True, slots=True)
class Candidate:
    """A validated hit, before overlap resolution and masking."""

    category_id: str
    category: CategoryConfig
    finding: Finding
    validators_passed: list[str]


@dataclass(frozen=True, slots=True)
class UnscannedCategory:
    category: str
    label: str
    reason: str


@dataclass(slots=True)
class ScanResult:
    path: Path
    matches: list[SensitiveMatch] = field(default_factory=list)
    unscanned_categories: list[UnscannedCategory] = field(default_factory=list)
    unreadable_pages: list[int] = field(default_factory=list)
    """Pages with no text at all, so nothing could be looked for on them."""
    pages_scanned: int = 0
    reveal_used: bool = False
    reveal_blocked_categories: list[str] = field(default_factory=list)

    @property
    def counts_by_category(self) -> dict[str, int]:
        return dict(Counter(m.category for m in self.matches))

    @property
    def counts_by_severity(self) -> dict[str, int]:
        return dict(Counter(m.severity for m in self.matches))

    @property
    def total(self) -> int:
        return len(self.matches)


def _line_starts(text: str) -> list[int]:
    starts = [0]
    for index, char in enumerate(text):
        if char == "\n":
            starts.append(index + 1)
    return starts


def _locate(starts: list[int], offset: int) -> tuple[int, int]:
    """(1-indexed line, 0-indexed column) for a character offset."""
    line_index = bisect_right(starts, offset) - 1
    return line_index + 1, offset - starts[line_index]


def _resolve_overlaps(
    candidates: list[Candidate],
) -> list[Candidate]:
    """Drop overlapping hits within the mutually exclusive identifier group."""
    exclusive = [c for c in candidates if c.category_id in _EXCLUSIVE_GROUP]
    independent = [c for c in candidates if c.category_id not in _EXCLUSIVE_GROUP]

    # Longest first, so a full card number beats a phone-shaped slice of it.
    exclusive.sort(
        key=lambda c: (c.finding.end - c.finding.start, c.finding.confidence), reverse=True
    )
    accepted: list[Candidate] = []
    taken: list[tuple[int, int]] = []
    for candidate in exclusive:
        span = (candidate.finding.start, candidate.finding.end)
        if any(span[0] < end and start < span[1] for start, end in taken):
            continue
        taken.append(span)
        accepted.append(candidate)

    return accepted + independent


def _scan_page(
    page_number: int,
    text: str,
    config: SensitiveConfig,
    reveal: bool,
    unavailable: dict[str, str],
) -> list[SensitiveMatch]:
    candidates: list[Candidate] = []

    for category_id, category in config.enabled_categories.items():
        if category_id in unavailable:
            continue
        engine = detector_by_id(category.detector)
        if engine is None:
            unavailable[category_id] = f"no detector named {category.detector!r} is registered"
            continue
        try:
            findings: list[Finding] = engine.find(text, DetectorContext(category_id, category))
        except DetectorUnavailableError as exc:
            unavailable[category_id] = str(exc)
            continue
        except Exception as exc:
            unavailable[category_id] = f"{type(exc).__name__}: {exc}"
            continue

        for finding in findings:
            # A detector with no score of its own cannot be filtered on one.
            # It is labelled instead, by its evidence tier.
            if finding.confidence is not None and finding.confidence < category.min_confidence:
                continue
            value = text[finding.start : finding.end]
            passed, names = validate(value, category.validators)
            if not passed:
                continue
            candidates.append(Candidate(category_id, category, finding, names))

    starts = _line_starts(text)
    matches: list[SensitiveMatch] = []
    for candidate in _resolve_overlaps(candidates):
        finding = candidate.finding
        value = text[finding.start : finding.end]
        masked, revealed = render(value, candidate.category_id, config.masking, reveal)
        line, column = _locate(starts, finding.start)
        matches.append(
            SensitiveMatch(
                category=candidate.category_id,
                label=candidate.category.label,
                severity=candidate.category.severity,
                page=page_number,
                line=line,
                column=column,
                length=len(value),
                masked=masked,
                revealed=revealed,
                confidence=finding.confidence,
                evidence=evidence_of(
                    candidate.category.detector,
                    candidate.validators_passed,
                    finding.context_term,
                ),
                validators_passed=candidate.validators_passed,
                context_term=finding.context_term,
            )
        )

    matches.sort(key=lambda m: (m.page, m.line, m.column))
    return matches


def scan(document: Document, config: SensitiveConfig, reveal: bool = False) -> ScanResult:
    result = ScanResult(path=document.path, reveal_used=reveal)
    unavailable: dict[str, str] = {}

    for page in document.pages:
        if not page.text.strip():
            result.unreadable_pages.append(page.number)
            continue
        result.pages_scanned += 1
        result.matches.extend(_scan_page(page.number, page.text, config, reveal, unavailable))

    for category_id, reason in unavailable.items():
        category = config.categories.get(category_id)
        result.unscanned_categories.append(
            UnscannedCategory(
                category=category_id,
                label=category.label if category else category_id,
                reason=reason,
            )
        )

    if reveal:
        result.reveal_blocked_categories = [
            c for c in config.masking.never_reveal if c in config.enabled_categories
        ]

    return result
