"""Global readiness: content, cost and exposure in one number.

AI readiness asks whether the text can be got off the page. That is the
largest question and not the only one — a folder that is legible, ruinous to
run and full of national insurance numbers is not ready either.

The line these tests hold is the same one the content score holds: a factor
nobody measured is dropped and the rest are renormalised, never counted as
nought, and the result says what it was built from.
"""

from __future__ import annotations

from complydoc.audit import run_audit
from complydoc.overall import band_of, overall_readiness
from tests.helpers import FIXTURES

ALL = ("cost", "readiness", "sensitive")


def scored(config, components=ALL, **kwargs):
    report = run_audit(FIXTURES, config, components, ocr=False, **kwargs)
    return overall_readiness(report, config.readiness.overall)


def test_a_full_run_measures_every_factor(config):
    result = scored(config)
    assert not result.partial
    assert [f.key for f in result.factors] == ["content", "cost", "exposure"]
    assert all(f.score is not None for f in result.factors)


def test_a_factor_nobody_measured_is_dropped_not_scored_nought(config):
    """`complydoc readiness` runs no cost estimate and no scan.

    Counting those as zero would report a folder as unusable because of two
    questions nobody asked.
    """
    partial = scored(config, ("readiness",))
    full = scored(config)

    assert partial.partial
    assert [f.key for f in partial.factors if not f.measured] == ["cost", "exposure"]
    assert partial.score is not None
    content = next(f for f in partial.factors if f.key == "content")
    assert partial.score == content.score, "one factor left, so it is the whole score"
    assert partial.score != full.score


def test_the_bands_count_documents_not_the_average(config):
    """The mean is one number and it hides the tail."""
    result = scored(config)
    assert sum(result.bands.values()) == result.scored_documents
    assert set(result.bands) <= {"ready", "workable", "needs work", "not ready"}


def test_the_score_reads_the_same_way_round_as_the_content_score(config):
    assert band_of(90) == "ready"
    assert band_of(60) == "workable"
    assert band_of(30) == "needs work"
    assert band_of(10) == "not ready"


def test_a_document_full_of_confirmed_identifiers_scores_below_a_clean_one(config):
    result = scored(config)
    exposure = next(f for f in result.factors if f.key == "exposure")
    assert exposure.score is not None
    assert exposure.score < 100, "the fixtures carry identifiers"


def test_a_scanned_folder_scores_worse_on_cost_than_a_native_one(config):
    """A page nothing can be read off has to be sent to a model as an image."""
    without = scored(config)
    cost = next(f for f in without.factors if f.key == "cost")
    assert cost.score is not None
    assert cost.score < 100, "some fixtures are scans with OCR off"


def test_the_weights_are_visible(config):
    """A score whose weights are not shown is what this tool refuses to emit."""
    result = scored(config)
    assert all(f.weight > 0 for f in result.factors)
    assert all(f.why for f in result.factors)


def test_turning_it_off_produces_no_score(config):
    from complydoc.config.schema import OverallConfig

    report = run_audit(FIXTURES, config, ALL, ocr=False)
    result = overall_readiness(report, OverallConfig(enabled=False))
    assert result.score is None
    assert not result.bands
