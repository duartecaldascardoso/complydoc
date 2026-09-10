"""Reading the text layer with more than one library.

Comparison lives inside a run: the same page, the same machine, the same moment.
Two runs of different extractors would differ for reasons that have nothing to
do with the extractors.

Only one extractor's reading reaches a finding. The rest are measured and
reported, and are never allowed to change what the report concludes.
"""

from __future__ import annotations

import pytest

from complydoc.audit import extractor_readings
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


def reading(
    name: str, characters: int, similarity: float = 1.0, reordered: bool = False
) -> ExtractorReading:
    return ExtractorReading(
        extractor=name,
        characters=characters,
        mean_coverage_pct=10.0,
        seconds=0.01,
        granularity="word",
        reads_tables=True,
        similarity=similarity,
        reordered=reordered,
    )


def test_the_registry_finds_the_readers_that_always_ship():
    ids = {e.id for e in all_extractors()}
    assert {"pdfplumber", "pdfium", "pypdf"} <= ids
    assert extractor_by_id(DEFAULT_EXTRACTOR) is not None


def test_every_extractor_declares_what_it_can_do():
    """A signal needs to know what was not available, not guess from an empty list."""
    for engine in all_extractors():
        assert isinstance(engine.provides_tables, bool)
        assert isinstance(engine.provides_raw_chars, bool)
        assert engine.granularity in {"word", "line", "none"}


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
        extractions=[reading("a", 1000), reading("b", 1050, similarity=0.99)],
    )
    assert not document.extractors_disagree


def test_the_same_characters_in_a_different_order_is_a_disagreement():
    """The case a character count cannot see.

    Two extractors read a two-column page. One reads down the columns, the
    other straight across the page, and every sentence in the second is
    interleaved with a sentence from the other column. Same characters, same
    count, and one of them is unreadable.
    """
    document = DocumentReport(
        path=FIXTURES / "x.pdf",
        relative_path="x.pdf",
        sha256="",
        format="pdf",
        page_count=1,
        page_count_known=True,
        extractions=[reading("a", 1000), reading("b", 1000, similarity=0.11, reordered=True)],
    )
    assert document.disagreement == "same words, different order"


def test_reading_different_words_is_not_called_a_reordering():
    """The two call for different things.

    A reader that scrambled a page it could otherwise read has a layout
    problem. A reader that returned different words could not read part of it.
    """
    document = DocumentReport(
        path=FIXTURES / "x.pdf",
        relative_path="x.pdf",
        sha256="",
        format="pdf",
        page_count=1,
        page_count_known=True,
        extractions=[reading("a", 1000), reading("b", 1000, similarity=0.80)],
    )
    assert document.disagreement == "they read different words"


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


def test_a_scrambled_two_column_page_is_caught_end_to_end():
    """The fixture that prompted the measure.

    pdfplumber reads the two columns in order; pdfium reads straight across
    and interleaves them. Their character counts are within a few percent of
    each other, so nothing about the size of the reading says they disagree.
    """
    document = load_document(
        FIXTURES / "two_column.pdf",
        IngestOptions(compare_extractors=("pdfium",)),
    )
    readings = extractor_readings(document)
    counts = [r.characters for r in readings]
    assert abs(counts[0] - counts[1]) / max(counts) < 0.10, "the counts do not give it away"
    assert min(r.similarity for r in readings) < 0.6
    report = DocumentReport(
        path=document.path,
        relative_path="two_column.pdf",
        sha256="",
        format="pdf",
        page_count=1,
        page_count_known=True,
        extractions=readings,
    )
    assert report.extractors_disagree


@pytest.mark.parametrize("name", ["pdfplumber", "pdfium"])
def test_either_extractor_can_read_a_plain_page(name):
    document = load_document(FIXTURES / "dense_text.pdf", IngestOptions(extractor=name))
    assert document.full_text.strip()
    assert document.pages[0].text_blocks


def test_a_reader_without_geometry_reports_no_coverage_rather_than_none_of_it():
    """pypdf returns text and no boxes.

    Nought per cent coverage would read as a page with nothing on it, which is
    the opposite of what happened.
    """
    document = load_document(FIXTURES / "dense_text.pdf", IngestOptions(extractor="pypdf"))
    summary = document.pages[0].extractions[0]
    assert summary.characters > 1000
    assert summary.coverage_pct is None


def test_the_signals_that_need_boxes_say_so_when_a_reader_has_none():
    config = load_config()
    document = load_document(FIXTURES / "dense_text.pdf", IngestOptions(extractor="pypdf"))
    result = analyse(document, config.readiness)
    assert any(s.rating is None for s in result.signals)


def test_three_readers_agree_that_the_default_one_scrambles_two_columns():
    """The finding this comparison exists to make.

    pdfplumber walks the text layer in file order, which on this page runs
    across both columns and interleaves every sentence with one from the other
    side. pdfium and pypdf share no code with it or with each other, and both
    read the columns in order.
    """
    document = load_document(
        FIXTURES / "two_column.pdf",
        IngestOptions(compare_extractors=("pdfium", "pypdf"), keep_readings=True),
    )
    readings = document.pages[0].readings
    others = [" ".join(readings[name].split()) for name in ("pdfium", "pypdf")]
    assert others[0][:60] == others[1][:60], "the two independent readers agree"
    assert " ".join(readings["pdfplumber"].split())[:60] != others[0][:60]
    assert min(r.similarity for r in extractor_readings(document)) < 0.6
