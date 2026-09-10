"""Page wireframes. The load-bearing property is that they carry no content."""

from __future__ import annotations

import json

import pytest

from complydoc.config.loader import load_config
from complydoc.report.html_writer import page_preview_svg
from complydoc.report.models import to_jsonable
from complydoc.report.preview import build_previews
from complydoc.sensitive.scanner import scan


@pytest.fixture(scope="module")
def config():
    return load_config()


def previews_for(loader, config, name):
    document = loader(name)
    return document, build_previews(document, scan(document, config.sensitive))


# --- the guarantee ---------------------------------------------------------


def test_preview_carries_no_document_text(loader, config):
    """A thumbnail of the page would undo the masking. Geometry must be numbers only."""
    _, previews = previews_for(loader, config, "sensitive_sample.pdf")
    serialised = json.dumps(to_jsonable(previews))
    for secret in ("4111", "AB123456C", "jane.doe", "GB82", "Jane", "Doe", "Acme"):
        assert secret not in serialised, f"{secret!r} reached the preview data"


def test_preview_svg_contains_no_text_elements(loader, config):
    _, previews = previews_for(loader, config, "sensitive_sample.pdf")
    svg = page_preview_svg(previews[0])
    assert "<text" not in svg
    assert "<image" not in svg, "no rasterised page may be embedded"


def test_preview_svg_is_self_contained(loader, config):
    _, previews = previews_for(loader, config, "native_text.pdf")
    svg = page_preview_svg(previews[0])
    assert "http" not in svg


# --- placement -------------------------------------------------------------


def test_sensitive_values_are_placed_on_the_page(loader, config):
    _, previews = previews_for(loader, config, "sensitive_sample.pdf")
    page = previews[0]
    assert page.sensitive_count > 10
    assert page.unlocated_sensitive == 0
    assert len(page.sensitive) == page.sensitive_count


def test_placed_boxes_are_inside_the_page(loader, config):
    _, previews = previews_for(loader, config, "sensitive_sample.pdf")
    for box in previews[0].sensitive:
        assert 0.0 <= box.x <= 1.0
        assert 0.0 <= box.y <= 1.0
        assert 0.0 < box.w <= 1.0
        assert 0.0 < box.h <= 1.0


def test_high_severity_is_distinguishable(loader, config):
    _, previews = previews_for(loader, config, "sensitive_sample.pdf")
    labels = {b.label for b in previews[0].sensitive}
    assert "high" in labels


def test_a_match_that_cannot_be_placed_is_counted_not_dropped(loader, config):
    """DOCX carries no word geometry, so nothing can be positioned."""
    _, previews = previews_for(loader, config, "sample.docx")
    page = previews[0]
    assert page.sensitive_count > 0
    assert page.sensitive == []
    assert page.unlocated_sensitive == page.sensitive_count


def test_implausible_box_is_rejected(loader, config):
    """A run of words spanning most of a page is not one identifier."""
    from complydoc.ingest.base import Rect
    from complydoc.report.preview import _plausible

    document = loader("two_column.pdf")
    page = document.pages[0]
    assert _plausible(Rect(10, 100, 60, 110), page) is True
    assert _plausible(Rect(10, 100, page.width_pt - 10, 110), page) is False, "too wide"
    assert _plausible(Rect(10, 100, 60, 400), page) is False, "too tall"


# --- what the picture says -------------------------------------------------


def test_a_scan_is_all_image_and_no_text(loader, config):
    _, previews = previews_for(loader, config, "scanned_page.pdf")
    page = previews[0]
    assert page.image_coverage_pct > 90
    assert page.text_blocks == []
    assert page.image_blocks


def test_a_text_page_is_all_text_and_no_image(loader, config):
    _, previews = previews_for(loader, config, "native_text.pdf")
    page = previews[0]
    assert page.text_blocks
    assert page.image_blocks == []


def test_a_two_column_page_shows_its_gutter(loader, config):
    _, previews = previews_for(loader, config, "two_column.pdf")
    assert len(previews[0].gutters) == 1
    gutter = previews[0].gutters[0]
    assert 0.3 < gutter.x < 0.7, "the gutter should sit near the middle"


def test_a_single_column_page_has_no_gutter(loader, config):
    _, previews = previews_for(loader, config, "native_text.pdf")
    assert previews[0].gutters == []


def test_rotation_is_carried_through(loader, config):
    _, previews = previews_for(loader, config, "rotated_scan.pdf")
    assert previews[0].rotation == 90


def test_one_preview_per_page(loader, config):
    document, previews = previews_for(loader, config, "mixed_page_sizes.pdf")
    assert len(previews) == document.page_count == 3
    assert [p.number for p in previews] == [1, 2, 3]


# --- page images are opt-in ------------------------------------------------


def test_no_page_image_by_default(loader, config):
    """The default report is forwardable, so it carries no picture of the page."""
    document = loader("sensitive_sample.pdf")
    previews = build_previews(document, scan(document, config.sensitive))
    assert all(p.image_data_uri is None for p in previews)


def test_page_images_are_embedded_when_asked_for():
    from complydoc.ingest.base import IngestOptions
    from complydoc.ingest.registry import load_document
    from tests.helpers import FIXTURES

    document = load_document(
        FIXTURES / "sensitive_sample.pdf",
        IngestOptions(render_all_pages=True, max_render_pages=10),
    )
    previews = build_previews(document, None, page_images=True)
    assert previews[0].image_data_uri is not None
    assert previews[0].image_data_uri.startswith("data:image/jpeg;base64,")


def test_a_format_with_no_raster_gets_no_image(loader, config):
    """DOCX is never rasterised, so there is nothing to show beside the extraction."""
    document = loader("sample.docx")
    previews = build_previews(document, scan(document, config.sensitive), page_images=True)
    assert previews[0].image_data_uri is None


def test_a_sensitive_mark_explains_itself(loader, config):
    """A rectangle on a wireframe says only that something was found.

    Pointing at it should answer what it is, why it was reported, and why that
    matters — none of which is the value.
    """
    from complydoc.report.preview import build_previews
    from complydoc.sensitive.scanner import scan

    document = loader("sensitive_sample.pdf")
    result = scan(document, config.sensitive)
    previews = build_previews(document, result, categories=config.sensitive)

    marks = [box for preview in previews for box in preview.sensitive]
    assert marks, "the fixture carries locatable identifiers"
    for box in marks:
        assert box.title
        heading, reason, *rest = box.title.split("\n")
        assert "severity" in heading
        assert reason.startswith(("Reported", "Recognised"))
        assert rest, "and why it matters at all"


def test_the_explanation_never_carries_the_value(loader, config):
    """The whole point of the wireframe is that it reproduces no content.

    Asserted on the explanation itself rather than by searching the output for
    the values: an organisation the model found may legitimately share words
    with a category's own label, and that is not a leak.
    """
    from complydoc.report.preview import _why_sensitive
    from complydoc.sensitive.scanner import scan

    document = loader("sensitive_sample.pdf")
    revealed = scan(document, config.sensitive, reveal=True)
    masked = scan(document, config.sensitive)

    assert any(m.revealed for m in revealed.matches), "there is something to leak"
    for hidden, shown in zip(masked.matches, revealed.matches, strict=True):
        assert _why_sensitive(hidden, config.sensitive) == _why_sensitive(
            shown, config.sensitive
        ), "the explanation changed when the value was unmasked"
        explanation = _why_sensitive(shown, config.sensitive)
        assert shown.masked not in explanation
        if shown.revealed and len(shown.revealed) > 6:
            assert shown.revealed not in explanation


def test_a_name_from_the_model_is_not_called_a_pattern(loader, config):
    from complydoc.report.preview import _why_sensitive
    from complydoc.sensitive.scanner import scan

    document = loader("sensitive_sample.pdf")
    result = scan(document, config.sensitive)
    ner = [m for m in result.matches if config.sensitive.categories[m.category].detector == "ner"]
    for match in ner:
        assert "pattern" not in _why_sensitive(match, config.sensitive)


def test_a_sensitive_mark_answers_the_pointer_across_its_whole_area():
    """An SVG shape with no fill answers the pointer only along its stroke.

    On a mark six pixels tall that is two hairlines, so pointing at the middle
    of one did nothing at all.
    """
    from complydoc.report import html_writer

    styles = (html_writer._TEMPLATE_DIR / "report.html.j2").read_text()
    assert ".pv-mark rect { pointer-events: all; }" in styles


def test_the_explanation_is_reachable_without_a_pointer():
    """A tooltip nobody can tab to is a tooltip some readers never get."""
    from complydoc.report import html_writer

    template = (html_writer._TEMPLATE_DIR / "report.html.j2").read_text()
    assert 'mark.setAttribute("tabindex", "0")' in template
    assert 'mark.addEventListener("focus", show)' in template
