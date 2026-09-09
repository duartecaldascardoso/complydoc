"""OCR text is a guess, and the engine says how sure it is."""

from __future__ import annotations

from complydoc.readiness.analyser import analyse
from complydoc.readiness.base import SignalStatus


def signal_for(loader, config, name):
    document = loader(name, ocr=True)
    return next(s for s in analyse(document, config.readiness).signals if s.id == "ocr_confidence")


def test_a_scanned_page_reports_the_engines_confidence(loader, config):
    signal = signal_for(loader, config, "scanned_page.pdf")
    assert signal.status is SignalStatus.MEASURED
    assert 0 < signal.value <= 100
    assert signal.detail["pages_measured"] >= 1


def test_confidence_is_not_invented_where_ocr_did_not_run(loader, config):
    signal = signal_for(loader, config, "native_text.pdf")
    assert signal.status is SignalStatus.NOT_APPLICABLE
    assert "did not run" in (signal.reason or "")


def test_the_worst_page_is_the_one_reported(loader, config):
    signal = signal_for(loader, config, "scanned_page.pdf")
    per_page = signal.detail["per_page"].values()
    assert signal.value == min(per_page)


def test_confidence_is_carried_on_the_page(loader):
    document = loader("scanned_page.pdf", ocr=True)
    page = document.pages[0]
    assert page.text_source == "ocr"
    assert page.ocr_confidence is not None
    assert 0.0 < page.ocr_confidence <= 1.0
