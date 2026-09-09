"""Garbled character rate: replacement characters, broken ligatures, lost spaces."""

from __future__ import annotations

import re

from complydoc.ingest.base import Document
from complydoc.readiness.base import ALL_FORMATS, Measurement
from complydoc.readiness.registry import signal

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
    why = "Replacement characters and lost spaces mean the text is not what is on the page."
    applies_to = ALL_FORMATS

    def measure(self, document: Document) -> Measurement:
        text = document.full_text
        if len(text) < _MIN_CHARS:
            return Measurement.na(
                f"only {len(text)} characters of text were available, which is too few "
                f"for a rate per 1,000 characters to mean anything"
            )

        replacements = text.count(_REPLACEMENT)
        run_together = _run_together(text)

        # Ligatures must be counted against the un-normalised characters. The
        # extractor's text assembly turns a fi ligature into "fi" before we ever
        # see it, so counting them in `text` would always return zero and this
        # line of the report would be quietly meaningless.
        raw = "".join(page.raw_chars for page in document.pages)
        ligature_source = "unnormalised page characters" if raw else "extracted text"
        ligatures = sum((raw or text).count(c) for c in _LIGATURES)
        total = replacements + ligatures + run_together
        rate = total / len(text) * 1000

        return Measurement(
            value=round(rate, 2),
            display=f"{rate:.1f} per 1,000 chars",
            detail={
                "characters_examined": len(text),
                "replacement_characters": replacements,
                "undecomposed_ligatures": ligatures,
                "ligature_source": ligature_source,
                "run_together_words": run_together,
                "total_indicators": total,
            },
        )
