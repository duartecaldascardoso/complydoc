"""Detected language per page."""

from __future__ import annotations

from collections import Counter

from complydoc.difficulty.base import ALL_FORMATS, Measurement
from complydoc.difficulty.registry import signal
from complydoc.ingest.base import Document

_MIN_LETTERS = 60
_MIN_LETTER_RATIO = 0.5


def _detect(text: str) -> str | None:
    try:
        import py3langid
    except ImportError:  # pragma: no cover - a core dependency
        return None
    try:
        language, _score = py3langid.classify(text)
    except Exception:
        return None
    return str(language)


@signal
class LanguageCountSignal:
    id = "language_count"
    name = "Languages detected"
    unit = "languages"
    why = "A pipeline tuned for one language lets a second pass through silently."
    applies_to = ALL_FORMATS

    def measure(self, document: Document) -> Measurement:
        per_page: dict[str, str] = {}
        skipped = 0
        for page in document.pages:
            text = page.text.strip()
            letters = sum(1 for c in text if c.isalpha())
            # A page of figures and table rules gets confidently classified as some
            # improbable language, so pages without enough prose are skipped rather
            # than reported.
            if letters < _MIN_LETTERS or not text or letters / len(text) < _MIN_LETTER_RATIO:
                skipped += 1
                continue
            detected = _detect(text)
            if detected:
                per_page[str(page.number)] = detected

        if not per_page:
            return Measurement.na(
                f"no page carried at least {_MIN_LETTERS} letters of prose that were also "
                f"at least {_MIN_LETTER_RATIO:.0%} of the page's characters, so any "
                f"language verdict would be noise"
            )

        counts = Counter(per_page.values())
        return Measurement(
            value=len(counts),
            display=(
                f"{next(iter(counts))} throughout"
                if len(counts) == 1
                else f"{len(counts)} languages: {', '.join(sorted(counts))}"
            ),
            detail={
                "per_page": per_page,
                "counts": dict(counts),
                "pages_measured": len(per_page),
                "pages_skipped_as_not_prose": skipped,
                "model": "py3langid, run locally",
            },
        )
