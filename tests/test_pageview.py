"""The page viewer: one page at a time, beside what was read off it.

The Documents page used to show a grid of the first twelve pages and keep the
extracted text in a separate tab, so a long document could not be walked through
and the page was never next to its own text. These pin the replacement.
"""

from __future__ import annotations

import re

import pytest

from complydoc.audit import COMPONENTS, run_audit
from complydoc.report.html_writer import page_rows, render_html
from tests.helpers import FIXTURES

MULTIPAGE = "mixed_page_sizes.pdf"
"""Three pages, each a different size — the fixture for traversal."""


def document_section(html: str) -> str:
    return html.split('id="documents"')[1].split("</main>")[0]


def spreads(html: str, path: str) -> list[str]:
    """The per-page panels of one document, in document order."""
    block = document_section(html).split(f"<h3>{path}</h3>")[1].split("<h3>")[0]
    return re.findall(r'<div class="spread" data-page="(\d+)"', block)


@pytest.fixture(scope="module")
def report(config):
    return run_audit(FIXTURES, config, COMPONENTS, ocr=True, extracted_text=True, page_images=True)


@pytest.fixture(scope="module")
def html(report, config):
    return render_html(report, config)


def test_every_page_is_reachable(html):
    """Not the first twelve — all of them, or you cannot check page 40."""
    assert spreads(html, MULTIPAGE) == ["1", "2", "3"]


def test_the_page_and_its_text_sit_in_one_panel(html):
    """Side by side is the whole point: the same panel holds both halves."""
    block = document_section(html).split(f"<h3>{MULTIPAGE}</h3>")[1].split("<h3>")[0]
    first = block.split('data-page="1"')[1].split('data-page="2"')[0]
    assert first.count('class="side"') == 2
    assert "<img" in first, "the page itself"
    assert "A4 page" in first, "the text read off that page"


def test_the_page_number_box_is_bounded_by_the_document(html):
    block = document_section(html).split(f"<h3>{MULTIPAGE}</h3>")[1].split("<h3>")[0]
    jump = block.split('class="pjump"')[1].split(">")[0]
    assert 'min="1"' in jump
    assert 'max="3"' in jump


def test_one_page_is_shown_and_the_rest_are_hidden(html):
    """The viewer is a viewer, not the old grid: JS reveals exactly one."""
    block = document_section(html).split(f"<h3>{MULTIPAGE}</h3>")[1].split("<h3>")[0]
    panels = re.findall(r'<div class="spread"[^>]*>', block)
    assert len(panels) == 3
    assert all("hidden" in panel for panel in panels)


def test_a_page_read_by_ocr_offers_no_comparison(html):
    """Its text layer IS the OCR output, so a switch would compare a thing to itself."""
    block = document_section(html).split("<h3>scanned_page.pdf</h3>")[1].split("<h3>")[0]
    assert 'data-face="ocr"' not in block
    assert "what OCR read from this page" in block


def test_ocr_compare_offers_both_readings(config):
    """With --ocr-compare the two are genuinely different and worth switching between."""
    # --ocr-compare implies --extracted-text on the command line; a library
    # caller has to ask for both, which is what the CLI does on its behalf.
    report = run_audit(
        FIXTURES, config, COMPONENTS, ocr=True, ocr_compare=True, extracted_text=True
    )
    html = render_html(report, config)
    block = document_section(html).split("<h3>native_text.pdf</h3>")[1].split("<h3>")[0]
    assert 'data-face="text"' in block
    assert 'data-face="ocr"' in block


def test_the_default_report_says_which_flag_shows_the_text(config):
    """Content is opt-in, so the empty half names the flag rather than sitting blank."""
    report = run_audit(FIXTURES, config, COMPONENTS)
    html = render_html(report, config)
    block = document_section(html).split(f"<h3>{MULTIPAGE}</h3>")[1].split("<h3>")[0]
    assert "--extracted-text" in block
    assert spreads(html, MULTIPAGE) == ["1", "2", "3"], "pages stay traversable regardless"


def test_page_rows_joins_the_page_to_its_own_text(report):
    """Previews and text are collected separately; they are matched by number."""
    document = next(d for d in report.documents if d.relative_path == MULTIPAGE)
    rows = page_rows(document)
    assert [r.number for r in rows] == [1, 2, 3]
    assert "A4" in rows[0].text and "A5" in rows[1].text
    assert all(r.preview is not None and r.preview.number == r.number for r in rows)


def test_page_rows_survives_a_document_with_no_text(config):
    document = next(
        d for d in run_audit(FIXTURES, config, COMPONENTS).documents if d.relative_path == MULTIPAGE
    )
    rows = page_rows(document)
    assert [r.number for r in rows] == [1, 2, 3]
    assert all(r.text == "" and r.preview is not None for r in rows)


def test_an_unreadable_document_yields_no_pages(report):
    document = next(d for d in report.documents if d.relative_path == "encrypted.pdf")
    assert page_rows(document) == []
