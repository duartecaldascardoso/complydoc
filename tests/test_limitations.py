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


def test_character_counts_describe_their_own_document(report):
    """A count in a reason must be the count for the document it sits on.

    An earlier revision grouped these by signal name and reused the first
    document's character count for every document in the group.
    """
    counts = {}
    for document in report.documents:
        if not document.difficulty:
            continue
        signal = next((s for s in document.difficulty.signals if s.id == "garbled_char_rate"), None)
        if signal and signal.reason and "only " in signal.reason:
            counts[document.relative_path] = signal.reason.split("only ")[1].split(" ")[0]
    assert len(counts) > 1
    assert len(set(counts.values())) > 1, "every document reported the same count"


def test_articles_read_as_english(report):
    """The reasons are generated, so the article has to be chosen, not hardcoded."""
    for entry in report.limitations:
        assert "a image" not in entry.statement
    reasons = [
        signal.reason or ""
        for document in report.documents
        if document.difficulty
        for signal in document.difficulty.signals
    ]
    assert any("an image file" in reason for reason in reasons)
    assert not any("a image" in reason for reason in reasons)


def test_signals_that_do_not_apply_are_not_run_level_limitations(report):
    """Eighteen per document buried everything that actually needed attention."""
    areas = {x.area for x in report.limitations}
    assert "Signals not measured" not in areas

    signals = {s.id for d in report.documents if d.difficulty for s in d.difficulty.signals}
    assert not areas & signals, "a signal became a run-level limitation"

    # The entries describe the run, so how many there are tracks the run's own
    # facts rather than the signals measured on each of its documents. The exact
    # number moves with which optional extras are installed — a detector that is
    # missing is itself a limitation — so the bound is on the shape, not a count.
    assert len(report.limitations) < len(report.documents) * 2


def test_a_signal_that_did_not_apply_still_says_why_on_its_document(report):
    document = next(d for d in report.documents if d.relative_path == "sample.docx")
    skipped = [s for s in document.difficulty.signals if s.rating is None]
    assert skipped
    assert all(s.reason for s in skipped)


def test_one_entry_per_distinct_tokenizer_note(report):
    """Models sharing a note get one entry between them, not one each."""
    notes = entries(report, "Token counting")
    assert notes
    statements = [n.statement for n in notes]
    assert len(statements) == len(set(statements)), "the same note was emitted twice"
    # Anthropic ships three models with identical wording; they must share an entry.
    anthropic = [n for n in notes if "Anthropic" in n.statement]
    assert len(anthropic) == 1
    assert len(anthropic[0].affected) >= 3


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


def test_alignment_tables_say_what_they_cannot_measure(report):
    """A table with no rules carries nothing to read a span from."""
    entry = next(x for x in report.limitations if x.area == "Table detection")
    assert "whitespace rather than ruling lines" in entry.statement
    assert "whitespace_table.pdf" in entry.affected
    assert "native_text.pdf" not in entry.affected, "prose is not a table"
