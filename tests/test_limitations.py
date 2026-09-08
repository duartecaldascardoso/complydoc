"""The generated limitations section, including two bugs it used to have."""

from __future__ import annotations

import pytest

from complydoc.audit import run_audit
from complydoc.difficulty.analyser import analyse
from complydoc.difficulty.base import SignalStatus
from tests.helpers import FIXTURES


@pytest.fixture(scope="module")
def report(config):
    return run_audit(FIXTURES, config)


def entries(report, area):
    return [x for x in report.limitations if x.area == area]


def test_each_reason_is_attributed_to_the_right_documents(report):
    """Grouping on the signal alone attached one document's reason to all of them.

    It produced entries telling the reader a PNG was skipped because "this is a
    docx file", which is simply false.
    """
    for entry in entries(report, "Signals not measured"):
        if "this is a docx file" in entry.statement:
            assert all(f.endswith(".docx") for f in entry.affected), entry.affected
        if "this is an image file" in entry.statement:
            assert all(f.endswith(".png") for f in entry.affected), entry.affected
        if "this is a xlsx file" in entry.statement:
            assert all(f.endswith(".xlsx") for f in entry.affected), entry.affected


def test_form_fields_reason_matches_the_document(report):
    """Only the encrypted PDF was skipped for being encrypted."""
    for entry in entries(report, "Signals not measured"):
        if "PDF form fields" in entry.statement and "encrypted" in entry.statement:
            assert entry.affected == ["encrypted.pdf"]


def test_character_counts_are_per_group_not_borrowed(report):
    """ "only N characters" must describe the documents it is attached to."""
    seen = [
        e
        for e in entries(report, "Signals not measured")
        if "Garbled character rate" in e.statement
    ]
    assert len(seen) > 1, "different character counts should not be merged into one entry"
    counts = {e.statement.split("only ")[1].split(" character")[0] for e in seen}
    assert len(counts) == len(seen), "each entry should carry its own count"


def test_articles_read_as_english(report):
    """The reasons are generated, so the article has to be chosen, not hardcoded."""
    for entry in report.limitations:
        assert "a image" not in entry.statement
        assert "a pdf, image" not in entry.statement
    assert any("an image file" in e.statement for e in report.limitations)


def test_one_entry_per_distinct_tokenizer_note(report):
    """Three models sharing a note should not produce three near-identical entries."""
    assert len(entries(report, "Token counting")) == 1


def test_an_unopenable_document_reports_no_table_count(loader, config):
    """Counting zero tables in a file nobody could open is a false measurement."""
    document = loader("encrypted.pdf")
    result = analyse(document, config.difficulty)
    signal = next(s for s in result.signals if s.id == "table_count")
    assert signal.status is SignalStatus.NOT_APPLICABLE
    assert "could not be opened" in (signal.reason or "")


def test_an_unopenable_document_scores_from_one_signal(loader, config):
    document = loader("encrypted.pdf")
    result = analyse(document, config.difficulty)
    assert result.score is not None
    assert result.score.signals_counted == 1
    assert result.score.low_confidence is True


def test_zero_tables_is_qualified_not_asserted(report):
    """Line-based detection misses whitespace-aligned tables, so zero is not "none"."""
    entry = next(x for x in report.limitations if x.area == "Table detection")
    assert "ruling lines" in entry.statement
    assert entry.severity == "important"
    assert "native_text.pdf" in entry.affected
