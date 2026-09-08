"""The deliberately awkward fixtures, which is where the signals earn their keep."""

from __future__ import annotations

from complydoc.difficulty.analyser import analyse
from complydoc.difficulty.base import SignalStatus


def measure(document, config, signal_id):
    report = analyse(document, config.difficulty)
    found = next((s for s in report.signals if s.id == signal_id), None)
    assert found is not None, f"{signal_id} was not reported at all"
    return found


# --- a scanned page ------------------------------------------------------


def test_scanned_page_reports_no_text_layer(loader, config):
    signal = measure(loader("scanned_page.pdf"), config, "text_layer_present")
    assert signal.value is False
    assert signal.rating == "poor"


def test_scanned_page_is_almost_entirely_image(loader, config):
    signal = measure(loader("scanned_page.pdf"), config, "image_area_ratio_pct")
    assert signal.value > 90
    assert signal.rating == "poor"


def test_scanned_page_reports_its_resolution(loader, config):
    signal = measure(loader("scanned_page.pdf"), config, "scan_dpi")
    assert signal.status is SignalStatus.MEASURED
    assert 190 <= signal.value <= 210, "fixture was rendered at 200 DPI"


def test_scan_dpi_does_not_apply_to_a_text_document(loader, config):
    """Resolution is meaningless where the page is not a picture."""
    signal = measure(loader("native_text.pdf"), config, "scan_dpi")
    assert signal.status is SignalStatus.NOT_APPLICABLE
    assert "not a picture" in (signal.reason or "") or "scanned image" in (signal.reason or "")


# --- a three-row merged header table -------------------------------------


def test_merged_header_depth_is_three(loader, config):
    signal = measure(loader("merged_header_table.pdf"), config, "table_max_header_depth")
    assert signal.value == 3, "two spanning rows plus the row of leaf labels"


def test_merged_cells_are_counted(loader, config):
    signal = measure(loader("merged_header_table.pdf"), config, "table_merged_cells")
    assert signal.value >= 3


def test_a_table_is_detected_at_all(loader, config):
    signal = measure(loader("merged_header_table.pdf"), config, "table_count")
    assert signal.value >= 1


def test_table_signals_do_not_apply_without_tables(loader, config):
    signal = measure(loader("native_text.pdf"), config, "table_merged_cells")
    assert signal.status is SignalStatus.NOT_APPLICABLE


# --- a two-column layout --------------------------------------------------


def test_two_column_layout_is_detected(loader, config):
    signal = measure(loader("two_column.pdf"), config, "column_count")
    assert signal.value == 2


def test_single_column_layout_is_not_a_false_positive(loader, config):
    signal = measure(loader("native_text.pdf"), config, "column_count")
    assert signal.value == 1
    assert signal.rating == "good"


# --- a rotated scan -------------------------------------------------------


def test_rotation_flag_is_reported(loader, config):
    signal = measure(loader("rotated_scan.pdf"), config, "page_rotation")
    assert signal.value == 90
    assert signal.rating == "poor"


def test_skew_is_measured_even_on_a_sideways_page(loader, config):
    """The fixture was skewed 3.5 degrees before being turned on its side."""
    signal = measure(loader("rotated_scan.pdf"), config, "skew_angle")
    assert signal.status is SignalStatus.MEASURED
    assert 3.0 <= signal.value <= 4.0, f"expected about 3.5 degrees, got {signal.value}"


def test_skew_does_not_apply_when_nothing_was_rasterised(loader, config):
    signal = measure(loader("native_text.pdf"), config, "skew_angle")
    assert signal.status is SignalStatus.NOT_APPLICABLE


# --- an encrypted PDF ------------------------------------------------------


def test_encrypted_pdf_is_reported_not_crashed(loader, config):
    signal = measure(loader("encrypted.pdf"), config, "encrypted")
    assert signal.value is True
    assert signal.rating == "poor"


def test_encrypted_pdf_excludes_unmeasurable_signals_from_its_score(loader, config):
    report = analyse(loader("encrypted.pdf"), config.difficulty)
    assert report.score is not None
    assert report.score.low_confidence is True
    assert report.score.signals_excluded > report.score.signals_counted


# --- garbled text ----------------------------------------------------------


def test_garbled_document_scores_poorly_on_garbling(loader, config):
    signal = measure(loader("garbled.pdf"), config, "garbled_char_rate")
    assert signal.rating == "poor"
    assert signal.detail["replacement_characters"] > 0
    assert signal.detail["undecomposed_ligatures"] > 0
    assert signal.detail["run_together_words"] > 0


def test_clean_document_has_no_garbling(loader, config):
    signal = measure(loader("native_text.pdf"), config, "garbled_char_rate")
    assert signal.value == 0
    assert signal.rating == "good"


# --- mixed page sizes -------------------------------------------------------


def test_mixed_page_sizes_are_counted(loader, config):
    signal = measure(loader("mixed_page_sizes.pdf"), config, "page_size_variance")
    assert signal.value == 3
    assert signal.rating == "poor"


# --- form fields are a positive signal ---------------------------------------


def test_form_fields_rate_as_good_not_bad(loader, config):
    signal = measure(loader("acroform.pdf"), config, "acroform_fields")
    assert signal.value == 5
    assert signal.rating == "good", "named form fields are the easy case, not a problem"


# --- language ----------------------------------------------------------------


def test_language_is_detected_on_prose(loader, config):
    signal = measure(loader("native_text.pdf"), config, "language_count")
    assert signal.value == 1
    assert signal.detail["per_page"]["1"] == "en"


def test_language_declines_to_guess_on_a_page_of_figures(loader, config):
    signal = measure(loader("merged_header_table.pdf"), config, "language_count")
    assert signal.status is SignalStatus.NOT_APPLICABLE


# --- calibration -----------------------------------------------------------


def test_a_realistically_dense_page_rates_good_for_coverage(loader, config):
    """The thresholds have to be set against a real page, not a sparse fixture.

    Every other text fixture here is fifteen lines on an A4 page and measures
    under 8%. Calibrating from those rated every genuine document "good" and made
    the signal meaningless, so this fixture is the reference point.
    """
    signal = measure(loader("dense_text.pdf"), config, "text_layer_coverage_pct")
    assert signal.value > 50, f"a full page of prose should be dense, got {signal.value}%"
    assert signal.rating == "good"


def test_a_page_that_is_a_picture_rates_poor_for_coverage(loader, config):
    signal = measure(loader("scanned_page.pdf"), config, "text_layer_coverage_pct")
    assert signal.value == 0
    assert signal.rating == "poor"


def test_dense_page_scores_well_overall(loader, config):
    from complydoc.difficulty.analyser import analyse

    report = analyse(loader("dense_text.pdf"), config.difficulty)
    assert report.score is not None
    assert report.score.value >= 75, "a clean dense text page should be straightforward"
