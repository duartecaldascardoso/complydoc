"""Garbled character rate: replacement characters, broken ligatures, lost spaces."""

from __future__ import annotations

import re

from complydoc.difficulty.base import ALL_FORMATS, Measurement
from complydoc.difficulty.registry import signal
from complydoc.ingest.base import Document

_REPLACEMENT = "�"
_LIGATURES = "ﬀﬁﬂﬃﬄﬅﬆ"
_TOKEN = re.compile(r"\S+")
_CAMEL_RUN = re.compile(r"[a-z][A-Z]")

_MIN_CHARS = 200
_LONG_TOKEN = 15
_VERY_LONG_TOKEN = 25


def _run_together(text: str) -> int:
    """Tokens that look like several words with the spaces lost between them."""
    count = 0
    for match in _TOKEN.finditer(text):
        token = match.group()
        if len(token) < _LONG_TOKEN or not any(c.isalpha() for c in token):
            continue
        if len(_CAMEL_RUN.findall(token)) >= 2 or (
            len(token) >= _VERY_LONG_TOKEN and token.isalpha()
        ):
            count += 1
    return count


@signal
class GarbledSignal:
    id = "garbled_char_rate"
    name = "Garbled character rate"
    unit = "per 1,000 characters"
    why = (
        "Replacement characters, ligatures that were never decomposed and words with "
        "their spaces lost all mean the extracted text does not match what a human sees "
        "on the page, so field values come out subtly wrong rather than obviously missing."
    )
    applies_to = ALL_FORMATS

    def measure(self, document: Document) -> Measurement:
        text = document.full_text
        if len(text) < _MIN_CHARS:
            return Measurement.na(
                f"only {len(text)} characters of text were available, which is too few "
                f"for a rate per 1,000 characters to mean anything"
            )

        replacements = text.count(_REPLACEMENT)
        ligatures = sum(text.count(c) for c in _LIGATURES)
        run_together = _run_together(text)
        total = replacements + ligatures + run_together
        rate = total / len(text) * 1000

        return Measurement(
            value=round(rate, 2),
            display=f"{rate:.2f} per 1,000 characters",
            detail={
                "characters_examined": len(text),
                "replacement_characters": replacements,
                "undecomposed_ligatures": ligatures,
                "run_together_words": run_together,
                "total_indicators": total,
            },
        )
