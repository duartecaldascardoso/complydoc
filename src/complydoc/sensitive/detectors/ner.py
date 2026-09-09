"""Person and organisation names, via a local statistical model.

spaCy is an optional extra. When it is missing, this raises DetectorUnavailableError
so the affected categories are reported as *not scanned* rather than as zero
found. Those are very different claims and only one of them is true.

The model runs entirely locally. It is downloaded once at install time, like any
other dependency, and never contacts anything at scan time.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from complydoc.sensitive.base import DetectorContext, Finding
from complydoc.sensitive.registry import DetectorUnavailableError, detector

_MAX_CHARS = 400_000
"""spaCy's default parser ceiling; longer pages are truncated and the scan says so."""

_MIN_ALPHA = 2
"""Entities with fewer real letters than this are noise, not names."""

_ACRONYM_MAX = 5
"""Single all-caps tokens up to this length are treated as field labels."""


@lru_cache(maxsize=4)
def _load(model_name: str) -> Any:
    try:
        import spacy
    except ImportError as exc:
        raise DetectorUnavailableError(
            "named entity recognition needs the optional NER extra "
            "(install with: uv sync --extra ner)"
        ) from exc
    try:
        # Entity recognition needs the embeddings and the entity head; the
        # tagger, the dependency parser, the attribute ruler and the lemmatiser
        # are a third of the run's time and nothing here reads their output.
        return spacy.load(
            model_name,
            exclude=["tagger", "parser", "attribute_ruler", "lemmatizer", "senter", "textcat"],
        )
    except OSError as exc:
        # `spacy download` shells out to pip, which a uv tool environment does
        # not have, so the instruction that works in a checkout does nothing for
        # anyone who installed complydoc as a tool. The README carries that one.
        raise DetectorUnavailableError(
            f"the local spaCy model {model_name!r} is not installed. In a checkout: "
            f"uv run python -m spacy download {model_name}. For a tool install, see "
            f"Install in the README"
        ) from exc


@lru_cache(maxsize=2)
def _parse(model_name: str, text: str) -> Any:
    """Run the model over one page, once.

    Every category that uses this detector asks about the same page, so without
    this the page is parsed once per category — twice over, for names and for
    organisations, at no benefit. The cache holds the page in hand and the one
    before it; it is not a store.
    """
    return _load(model_name)(text)


def model_available(model_name: str) -> tuple[bool, str | None]:
    try:
        _load(model_name)
    except DetectorUnavailableError as exc:
        return False, str(exc)
    return True, None


@detector
class NerDetector:
    id = "ner"

    def find(self, text: str, context: DetectorContext) -> list[Finding]:
        spec = context.config.model
        if spec is None:
            raise DetectorUnavailableError(
                f"category {context.category_id!r} uses the NER detector but names no model"
            )
        wanted = {label.upper() for label in spec.entity_labels}

        findings: list[Finding] = []
        document = _parse(spec.name, text[:_MAX_CHARS])
        for entity in document.ents:
            if entity.label_.upper() not in wanted:
                continue
            span = entity.text
            # An entity straddling a line break is almost always an artefact of
            # reading a laid-out page as flat text: the model has run the end of
            # one line into the start of the next and named the result. Reporting
            # "Jane Doe / Employer" as one person's name helps nobody.
            if "\n" in span or "\r" in span:
                continue
            if sum(1 for c in span if c.isalpha()) < _MIN_ALPHA:
                continue
            # Forms are full of short upper-case field labels — IBAN, VAT, UTR —
            # and the model reliably mistakes them for organisation names. A real
            # organisation written in capitals is virtually always more than one
            # word, so single short all-caps tokens are dropped.
            if len(span) <= _ACRONYM_MAX and span.isupper() and " " not in span.strip():
                continue
            findings.append(Finding(start=entity.start_char, end=entity.end_char, confidence=1.0))
        return findings
