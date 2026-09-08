"""Paths and skip markers shared across the test suite."""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def spacy_model_available() -> bool:
    from complydoc.sensitive.detectors.ner import model_available

    ok, _ = model_available("en_core_web_sm")
    return ok


requires_ner = pytest.mark.skipif(
    not spacy_model_available(),
    reason="the optional NER extra and en_core_web_sm are not installed",
)
