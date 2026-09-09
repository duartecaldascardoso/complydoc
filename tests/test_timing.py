"""Time is measured on the machine that ran the audit, not modelled."""

from __future__ import annotations

import pytest

from complydoc.audit import run_audit
from complydoc.text import duration
from tests.helpers import FIXTURES


@pytest.fixture(scope="module")
def report(config):
    return run_audit(FIXTURES, config, ocr=True)


def test_every_document_is_timed(report):
    assert all(d.timing is not None for d in report.documents)
    for document in report.documents:
        assert document.timing.total_seconds >= 0


def test_phases_add_up_to_the_total(report):
    for document in report.documents:
        t = document.timing
        assert t.total_seconds == pytest.approx(
            t.read_seconds + t.analyse_seconds + t.scan_seconds, abs=0.01
        )


def test_the_folder_total_is_the_sum_of_its_documents(report):
    total = sum(d.timing.total_seconds for d in report.documents)
    assert report.aggregate.total_seconds == pytest.approx(total, abs=0.01)


def test_per_document_and_per_page_rates_are_derived(report):
    aggregate = report.aggregate
    assert aggregate.seconds_per_document == pytest.approx(
        aggregate.total_seconds / aggregate.documents_audited, abs=0.01
    )
    assert aggregate.seconds_per_page == pytest.approx(
        aggregate.total_seconds / aggregate.pages_total, abs=0.01
    )


def test_the_backlog_projection_follows_the_measured_rate(report):
    aggregate = report.aggregate
    assert aggregate.hours_per_1000_documents == pytest.approx(
        aggregate.seconds_per_document * 1000 / 3600, abs=0.01
    )


def test_ocr_throughput_is_observed_not_assumed(report):
    """OCR dominates the clock on scans, and its speed is a property of the machine."""
    aggregate = report.aggregate
    if aggregate.ocr_pages:
        assert aggregate.ocr_seconds > 0
        assert aggregate.ocr_pages_per_second == pytest.approx(
            aggregate.ocr_pages / aggregate.ocr_seconds, abs=0.05
        )


def test_scans_take_longer_to_read_than_a_text_page(report):
    """The point of measuring: a scan is not the same unit of work as a text page."""
    by_name = {d.relative_path: d for d in report.documents}
    scan = by_name["scanned_page.pdf"].timing
    text = by_name["native_text.pdf"].timing
    assert scan.read_seconds > text.read_seconds


def test_counters_reset_between_runs(config):
    first = run_audit(FIXTURES, config, ocr=True)
    second = run_audit(FIXTURES, config, ocr=True)
    assert second.aggregate.ocr_pages == first.aggregate.ocr_pages


# --- formatting ------------------------------------------------------------


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (None, "—"),
        (0.004, "4ms"),
        (3.7, "3.7s"),
        (95, "2m"),
        (5400, "1.5h"),
        (200_000, "2.3 days"),
    ],
)
def test_durations_read_at_every_scale(seconds, expected):
    assert duration(seconds) == expected


# --- the honest gap --------------------------------------------------------


def test_model_time_is_not_estimated_without_a_measured_throughput(report):
    """complydoc cannot benchmark a hosted model offline, so it does not guess."""
    for document in report.documents:
        if document.cost:
            for model in document.cost.models:
                assert model.text_path_seconds is None


def test_model_time_is_estimated_once_a_throughput_is_configured(config, loader):
    from complydoc.config.schema import PricingConfig
    from complydoc.cost.estimator import estimate_document

    raw = config.pricing.model_dump()
    for entry in raw["models"]:
        entry["input_tokens_per_second"] = 1000.0
    pricing = PricingConfig.model_validate(raw)

    estimate = estimate_document(loader("native_text.pdf"), pricing)
    model = estimate.models[0]
    assert model.text_path_seconds == pytest.approx(model.text_tokens / 1000.0, abs=0.01)
