"""Reading one page with several readers, and keeping what each made of it.

The point is to see the difference, not just measure it: a character count says
two readers disagreed, and the text says how. Only the selected reader's output
reaches a finding.
"""

from __future__ import annotations

import pytest

from complydoc.audit import COMPONENTS, run_audit
from complydoc.ingest.base import IngestOptions
from complydoc.ingest.engines.base import Recognised
from complydoc.ingest.registry import load_document
from tests.helpers import FIXTURES


@pytest.fixture
def stub_engine(monkeypatch):
    """A second OCR engine, so the comparison can be exercised without one installed."""

    class StubEngine:
        id = "stub"
        name = "stub"

        def available(self) -> bool:
            return True

        def unavailable_reason(self) -> str | None:
            return None

        def set_threads(self, count: int | None) -> None:
            return None

        def read(self, image) -> Recognised:
            return Recognised("STUB ENGINE READING", 0.5, 3)

    from complydoc.ingest.engines import registry

    engine = StubEngine()
    monkeypatch.setitem(registry._ENGINES, "stub", engine)
    registry._discovered = True
    return engine


def test_a_default_run_keeps_no_extra_readings():
    """Several readings of every page is the largest thing a comparison adds."""
    document = load_document(FIXTURES / "dense_text.pdf", IngestOptions())
    assert document.pages[0].readings == {}


def test_comparing_extractors_keeps_what_each_read():
    document = load_document(
        FIXTURES / "dense_text.pdf",
        IngestOptions(compare_extractors=("pdfium",), keep_readings=True),
    )
    readings = document.pages[0].readings
    assert set(readings) == {"pdfplumber", "pdfium"}
    assert readings["pdfplumber"] != readings["pdfium"], "or there is nothing to compare"
    assert all(text.strip() for text in readings.values())


def test_the_kept_reading_is_the_one_the_findings_use():
    document = load_document(
        FIXTURES / "dense_text.pdf",
        IngestOptions(compare_extractors=("pdfium",), keep_readings=True),
    )
    page = document.pages[0]
    assert page.text == page.readings["pdfplumber"]


def test_measuring_without_keeping_text_keeps_no_text(config):
    """The counts are cheap; the readings are the document over again."""
    report = run_audit(
        FIXTURES / "dense_text.pdf",
        config,
        COMPONENTS,
        ocr=False,
        extracted_text=False,
        compare_extractors=("pdfium",),
    )
    document = report.documents[0]
    assert len(document.extractions) == 2, "still measured"
    assert not document.extracted_text, "and nothing kept"


def test_a_second_ocr_engine_reading_is_kept(stub_engine):
    """OCR engines genuinely disagree, which is what makes this worth showing."""
    document = load_document(
        FIXTURES / "scanned_page.pdf",
        IngestOptions(ocr=True, compare_engines=("stub",), keep_readings=True),
    )
    page = document.pages[0]
    assert page.readings.get("stub") == "STUB ENGINE READING"
    assert page.text != "STUB ENGINE READING", "a second opinion is not adopted"


def test_a_second_engine_is_not_run_when_nothing_is_kept(stub_engine):
    document = load_document(
        FIXTURES / "scanned_page.pdf",
        IngestOptions(ocr=True, compare_engines=("stub",), keep_readings=False),
    )
    assert "stub" not in document.pages[0].readings


def test_the_readings_reach_the_report(config):
    report = run_audit(
        FIXTURES / "dense_text.pdf",
        config,
        COMPONENTS,
        ocr=False,
        extracted_text=True,
        compare_extractors=("pdfium",),
    )
    page = report.documents[0].extracted_text[0]
    assert set(page.readings) == {"pdfplumber", "pdfium"}
    assert report.run.compare_extractors == ["pdfium"]
