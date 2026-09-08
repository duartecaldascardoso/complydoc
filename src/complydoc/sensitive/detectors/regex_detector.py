"""Pattern-based detection for the structured UK identifiers.

Two kinds of pattern are supported. `patterns` are distinctive enough to report
on sight. `context_patterns` are bare runs of digits that would carpet a business
document with false positives, so they are only reported when a label such as
"account number" appears within a short window.
"""

from __future__ import annotations

import re
from functools import lru_cache

from complydoc.sensitive.base import DetectorContext, Finding
from complydoc.sensitive.registry import detector

_CONTEXT_CONFIDENCE = 0.8


@lru_cache(maxsize=256)
def _compiled(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


def _nearby_term(
    text: str, start: int, end: int, terms: tuple[str, ...], window: int
) -> str | None:
    """The first configured label found within `window` characters of the match."""
    if not terms:
        return None
    left = max(0, start - window)
    haystack = text[left:start].lower() + " " + text[end : end + window].lower()
    for term in terms:
        if term.lower() in haystack:
            return term
    return None


@detector
class RegexDetector:
    id = "regex"

    def find(self, text: str, context: DetectorContext) -> list[Finding]:
        config = context.config
        findings: list[Finding] = []

        for pattern in config.patterns:
            for match in _compiled(pattern).finditer(text):
                findings.append(Finding(start=match.start(), end=match.end(), confidence=1.0))

        if config.context_patterns:
            terms = tuple(config.context_terms)
            for pattern in config.context_patterns:
                for match in _compiled(pattern).finditer(text):
                    term = _nearby_term(
                        text, match.start(), match.end(), terms, config.context_window_chars
                    )
                    if term is None:
                        continue
                    findings.append(
                        Finding(
                            start=match.start(),
                            end=match.end(),
                            confidence=_CONTEXT_CONFIDENCE,
                            context_term=term,
                        )
                    )
        return findings
