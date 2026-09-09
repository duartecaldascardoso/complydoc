"""Reading the text layer with more than one library.

Comparison lives inside a run: the same page, the same machine, the same moment.
Two runs of different extractors would differ for reasons that have nothing to
do with the extractors.

Only one extractor's reading reaches a finding. The rest are measured and
reported, and are never allowed to change what the report concludes.
"""

from __future__ import annotations

import pytest

from complydoc.config.loader import load_config
from complydoc.ingest.base import IngestOptions
from complydoc.ingest.extractors.registry import (
    DEFAULT_EXTRACTOR,
    all_extractors,
    extractor_by_id,
)
from complydoc.ingest.registry import load_document
from complydoc.readiness.analyser import analyse
from complydoc.report.models import DocumentReport, ExtractorReading
from tests.helpers import FIXTURES


def reading(name: str, characters: int) -> ExtractorReading:
    return ExtractorReading(
        extractor=name,
        characters=characters,
        mean_coverage_pct=10.0,
        seconds=0.01,
        granularity="word",
        reads_tables=True,
    )


def test_the_registry_finds_both_extractors():
    ids = {e.id for e in all_extractors()}
    assert {"pdfplumber", "pdfium"} <= ids
    assert extractor_by_id(DEFAULT_EXTRACTOR) is not None


def test_every_extractor_declares_what_it_can_do():
    """A signal needs to know what was not available, not guess from an empty list."""
    for engine in all_extractors():
        assert isinstance(engine.provides_tables, bool)
        assert isinstance(engine.provides_raw_chars, bool)
        assert engine.granularity in {"word", "line"}


def test_the_default_run_uses_one_extractor_and_says_which():
    document = load_document(FIXTURES / "native_text.pdf", IngestOptions())
    names = [s.extractor for page in document.pages for s in page.extractions]
    assert set(names) == {DEFAULT_EXTRACTOR}


def test_comparing_does_not_change_what_was_kept():
    """The whole safety property: a second opinion is recorded, never adopted."""
    alone = load_document(FIXTURES / "dense_text.pdf", IngestOptions())
    compared = load_document(
        FIXTURES / "dense_text.pdf", IngestOptions(compare_extractors=("pdfium",))
    )
    assert compared.full_text == alone.full_text
    assert len(compared.pages[0].text_blocks) == len(alone.pages[0].text_blocks)
    assert [s.extractor for s in compared.pages[0].extractions] == ["pdfplumber", "pdfium"]


def test_a_leaner_extractor_reports_what_it_could_not_measure():
    """It reads no table structure, so zero tables would be a false measurement."""
    config = load_config()
    document = load_document(
        FIXTURES / "merged_header_table.pdf", IngestOptions(extractor="pdfium")
    )
    result = analyse(document, config.readiness)
    table_signals = [s for s in result.signals if s.id.startswith("table")]
    assert table_signals
    for signal in table_signals:
        assert signal.rating is None, signal.id
        assert "does not read table structure" in (signal.reason or "") or "no tables" in (
            signal.reason or ""
        )


def test_the_richer_extractor_still_measures_them():
    config = load_config()
    document = load_document(FIXTURES / "merged_header_table.pdf", IngestOptions())
    result = analyse(document, config.readiness)
    counted = next(s for s in result.signals if s.id == "table_count")
    assert counted.rating is not None


def test_a_small_difference_is_not_reported_as_a_disagreement():
    """Line endings and whitespace differ on every document; saying so is noise."""
    document = DocumentReport(
        path=FIXTURES / "x.pdf",
        relative_path="x.pdf",
        sha256="",
        format="pdf",
        page_count=1,
        page_count_known=True,
        extractions=[reading("a", 1000), reading("b", 1050)],
    )
    assert not document.extractors_disagree


def test_a_large_difference_is():
    document = DocumentReport(
        path=FIXTURES / "x.pdf",
        relative_path="x.pdf",
        sha256="",
        format="pdf",
        page_count=1,
        page_count_known=True,
        extractions=[reading("a", 1000), reading("b", 400)],
    )
    assert document.extractors_disagree


def test_one_reading_nothing_at_all_is_always_a_disagreement():
    """The case that matters most: one of them could not read the page."""
    document = DocumentReport(
        path=FIXTURES / "x.pdf",
        relative_path="x.pdf",
        sha256="",
        format="pdf",
        page_count=1,
        page_count_known=True,
        extractions=[reading("a", 12), reading("b", 0)],
    )
    assert document.extractors_disagree


def test_a_single_extractor_never_disagrees_with_itself():
    document = DocumentReport(
        path=FIXTURES / "x.pdf",
        relative_path="x.pdf",
        sha256="",
        format="pdf",
        page_count=1,
        page_count_known=True,
        extractions=[reading("a", 1000)],
    )
    assert not document.extractors_disagree


@pytest.mark.parametrize("name", ["pdfplumber", "pdfium"])
def test_either_extractor_can_read_a_plain_page(name):
    document = load_document(FIXTURES / "dense_text.pdf", IngestOptions(extractor=name))
    assert document.full_text.strip()
    assert document.pages[0].text_blocks
