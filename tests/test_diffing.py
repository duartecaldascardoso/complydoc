"""Showing where two readings of a page part company.

Knowing that two readers disagree is the measurement; this is the part someone
can act on. The line these tests hold is that the marks appear where the
readers actually differ and nowhere else — a diff that marks every page for
line breaks is worse than no diff, because it is read as noise and ignored.
"""

from __future__ import annotations

from complydoc.ingest.base import Document, IngestOptions
from complydoc.ingest.registry import load_document
from complydoc.report.diffing import compare_readings
from complydoc.report.html_writer import page_rows
from complydoc.report.models import DocumentReport, PageText
from tests.helpers import FIXTURES


def only(kind: str, diff: object) -> str:
    return "".join(s.text for s in diff.segments if s.kind == kind)


def test_the_same_words_spaced_differently_are_not_a_difference():
    """Every reader breaks lines somewhere slightly different.

    A comparison that counted that would mark every page of every document,
    and a mark on every page is a mark on none of them.
    """
    kept = "the supplier shall provide\nthe services described"
    other = "the supplier shall\nprovide the services   described\n"
    diff = compare_readings(kept, {"other": other})[0]
    assert not diff.differs
    assert diff.similarity == 1.0


def test_a_word_only_one_reader_found_is_marked_as_added():
    diff = compare_readings("payable within fourteen days", {"other": "payable within 14 days"})[0]
    assert "14" in only("added", diff)
    assert "fourteen" in only("missing", diff)
    assert diff.added_words == 1
    assert diff.missing_words == 1


def test_the_marked_text_still_reads_as_the_page():
    """The pane is the reader's own text with marks on it, not a diff listing.

    Someone comparing wants to read the page and see what moved, so joining
    every segment has to give back what that reader read.
    """
    other = "payable within 14 days of the date"
    diff = compare_readings("payable within fourteen days of the date", {"other": other})[0]
    rebuilt = "".join(s.text for s in diff.segments if s.kind != "missing")
    assert " ".join(rebuilt.split()) == other


def test_a_reader_that_read_nothing_is_all_missing():
    diff = compare_readings("some text on the page", {"other": ""})[0]
    assert diff.differs
    assert only("added", diff) == ""
    assert diff.missing_words == 5


def test_the_two_column_page_is_the_one_that_gets_marked():
    """The case the whole comparison exists for.

    Only the page where a reader walked the columns in the wrong order should
    carry marks; the fixtures that every reader agrees on should carry none.
    """
    options = IngestOptions(compare_extractors=("pypdf",), keep_readings=True)
    scrambled = page_rows(_report(load_document(FIXTURES / "two_column.pdf", options)))
    plain = page_rows(_report(load_document(FIXTURES / "dense_text.pdf", options)))

    assert scrambled[0].readers_differ
    assert not plain[0].readers_differ
    assert scrambled[0].diffs[0].added_words > 20


def _report(document: Document) -> DocumentReport:
    """The smallest report entry `page_rows` needs."""
    return DocumentReport(
        path=document.path,
        relative_path=document.path.name,
        sha256="",
        format="pdf",
        page_count=len(document.pages),
        page_count_known=True,
        extracted_text=[
            PageText(
                number=page.number,
                source=page.text_source,
                characters=len(page.text),
                text=page.text,
                readings=dict(page.readings),
            )
            for page in document.pages
        ],
    )
