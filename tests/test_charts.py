"""Architecture cost comparison and the charts drawn from it."""

from __future__ import annotations

import re

import pytest

from complydoc.audit import run_audit
from complydoc.report.charts import SERIES, build_comparison, grouped_bars_svg
from tests.helpers import FIXTURES


@pytest.fixture(scope="module")
def comparisons(config):
    return build_comparison(run_audit(FIXTURES, config, ocr=True, monthly_volume=1000))


def test_every_priced_model_is_compared(comparisons, config):
    assert {c.model_id for c in comparisons} == {m.id for m in config.pricing.usable_models}


def test_all_three_architectures_are_costed(comparisons):
    for comparison in comparisons:
        assert [a.key for a in comparison.architectures] == [k for k, _, _ in SERIES]


def test_vision_costs_more_than_text(comparisons):
    """Where a model can do both. Some read text only, and have no vision cost
    at all rather than a cost of zero."""
    compared = 0
    for comparison in comparisons:
        text = comparison.by_key("text_ocr")
        vision = comparison.by_key("vision")
        if text.folder_usd is None or vision.folder_usd is None:
            continue
        compared += 1
        assert vision.folder_usd > text.folder_usd, comparison.model_id
    assert compared, "no model in the comparison could do both"


def test_a_text_only_model_has_no_vision_cost_rather_than_zero(comparisons):
    """It is a real choice for the cheapest path, and free is not what it is."""
    text_only = [c for c in comparisons if c.by_key("vision").folder_usd is None]
    for comparison in text_only:
        vision = comparison.by_key("vision")
        assert vision.folder_usd is None
        assert vision.per_1000_usd is None
        assert comparison.by_key("text_ocr").folder_usd is not None


def test_ocr_reaches_more_documents_than_the_text_layer_alone(comparisons):
    """The whole point of showing reach: cheapest is not the same as most useful."""
    for comparison in comparisons:
        assert (
            comparison.by_key("text_ocr").documents_served
            > comparison.by_key("text_layer").documents_served
        )


def test_reach_never_exceeds_the_folder(comparisons):
    for comparison in comparisons:
        for architecture in comparison.architectures:
            assert 0 <= architecture.documents_served <= architecture.documents_total


def test_cost_scales_with_price(comparisons):
    by_id = {c.model_id: c for c in comparisons}
    opus = by_id["claude-opus-5"].by_key("vision").folder_usd
    haiku = by_id["claude-haiku-4-5"].by_key("vision").folder_usd
    assert opus == pytest.approx(haiku * 5, rel=1e-6)


def test_annual_needs_a_volume(config):
    without = build_comparison(run_audit(FIXTURES, config, ocr=True))
    assert all(a.annual_usd is None for c in without for a in c.architectures)


# --- the drawing -----------------------------------------------------------


def test_chart_is_inline_svg_with_no_external_reference(comparisons):
    svg = grouped_bars_svg(comparisons, "folder_usd", "t")
    assert svg.startswith("<svg")
    assert "http" not in svg.replace('xmlns="http://www.w3.org/2000/svg"', "")


def test_every_bar_carries_a_direct_label(comparisons):
    """Two of the three series sit below 3:1 on the page, so labels are required."""
    svg = grouped_bars_svg(comparisons, "folder_usd", "t")
    bars = svg.count("<path")
    labels = len(re.findall(r">\$[\d,.]+<", svg))
    assert labels == bars


def test_one_precision_across_a_whole_chart(comparisons):
    """Mixing $0.00848 and $0.01 reads as two accuracies when it is one."""
    svg = grouped_bars_svg(comparisons, "folder_usd", "t")
    decimals = {len(v.split(".")[1]) for v in re.findall(r">\$([\d,.]+)<", svg) if "." in v}
    assert len(decimals) == 1


def test_series_colours_avoid_the_status_palette(comparisons):
    """Green, amber and red mean good, fair and poor everywhere else in the report."""
    colours = {c.lower() for _, _, c in SERIES}
    assert not colours & {"#1a7f4b", "#8a5a00", "#b3261e"}


def test_empty_input_draws_nothing(comparisons):
    assert grouped_bars_svg([], "folder_usd", "t") == ""
