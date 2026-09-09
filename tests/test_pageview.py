"""The page viewer: one page at a time, beside what was read off it.

The Documents page used to show a grid of the first twelve pages and keep the
extracted text in a separate tab, so a long document could not be walked through
and the page was never next to its own text. These pin the replacement.
"""

from __future__ import annotations

import base64
import io
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


def test_both_halves_share_one_framed_row(html):
    """Alignment is structural: every view of a page is framed the same way.

    The two frames are laid out as one row of equal height, so the page and the
    text it produced end at the same line and each scrolls inside its own box.
    """
    block = document_section(html).split(f"<h3>{MULTIPAGE}</h3>")[1].split("<h3>")[0]
    first = block.split('data-page="1"')[1].split('data-page="2"')[0]
    assert first.count('class="side"') == 2
    # One frame per switchable view: the page, its layout, and the text.
    assert first.count('class="face"') == first.count('class="body"') == 3


def test_provenance_lives_in_the_footer_only(html, report):
    """The page carried a heading repeating the path, the time and the version.

    None of it told a reader anything they had not just decided for themselves,
    and it pushed the actual content down the screen. It is recorded once, in
    the footer, where provenance belongs.
    """
    # The <title> still names the folder — that is how a browser tab is
    # identified — so only what is drawn on the page is checked here.
    above_the_tabs = html.split("</head>")[1].split('id="tabs"')[0]
    assert report.run.target not in above_the_tabs
    assert report.run.finished_at not in above_the_tabs
    assert "Document audit" not in above_the_tabs

    footer = html.split("<footer>")[1]
    assert report.run.target in footer
    assert report.run.finished_at in footer
    assert report.run.tool_version in footer


def test_the_page_image_declares_its_size(html):
    """Without it the frame is the wrong height until the image decodes.

    The panel beside it is laid out against that height, so it jumped every time
    a document was opened.
    """
    block = document_section(html).split(f"<h3>{MULTIPAGE}</h3>")[1].split("<h3>")[0]
    first = block.split('data-page="1"')[1].split('data-page="2"')[0]
    tag = first.split("<img")[1].split(">")[0]
    assert 'width="' in tag and 'height="' in tag


def test_the_recorded_size_is_the_size_it_was_encoded_at(report):
    from PIL import Image

    document = next(d for d in report.documents if d.relative_path == MULTIPAGE)
    for row in page_rows(document):
        assert row.image_width_px and row.image_height_px
        raw = base64.b64decode(row.image_data_uri.split(",", 1)[1])
        with Image.open(io.BytesIO(raw)) as decoded:
            assert (decoded.width, decoded.height) == (row.image_width_px, row.image_height_px)


def test_the_page_bar_is_one_control(html):
    """Three controls sitting near each other read as three controls."""
    block = document_section(html).split(f"<h3>{MULTIPAGE}</h3>")[1].split("<h3>")[0]
    nav = block.split('class="pnav"')[1].split("</div>")[0]
    assert nav.count('class="pstep"') == 2
    # The counter is one segment between the arrows, so it sits centred rather
    # than pinned to the left of a fixed-width box.
    counter = nav.split('class="pmid"')[1]
    assert 'class="pjump"' in counter
    assert 'class="pof"' in counter


def test_the_page_is_the_first_thing_on_the_page(html):
    """A pile of prose between the filename and the page defeated the point.

    Everything the preamble said — the format, the score, how long it took, the
    signals rated poor — is a question the signals tab answers, so it is asked
    there instead.
    """
    documents = document_section(html)
    assert "Difficulty signals across the whole folder" not in documents
    block = documents.split(f"<h3>{MULTIPAGE}</h3>")[1].split("<h3>")[0]
    preamble = block.split('class="spread"')[0]
    assert "to read and analyse" not in preamble
    assert 'class="concerns"' not in preamble


def test_what_the_preamble_used_to_say_is_still_reachable(html):
    block = document_section(html).split(f"<h3>{MULTIPAGE}</h3>")[1].split("<h3>")[0]
    # The first match is the tab button; the second is the panel it reveals.
    signals = block.split('<div data-view="signals"')[1]
    assert "to read and analyse" in signals
    assert "straightforward" in signals or "workable" in signals or "difficult" in signals


def test_the_layout_key_sits_outside_the_panels(html):
    """Inside the layout view it changed the height when you switched views.

    Constant geometry beats putting it next to what it describes: the layout is
    one click away from wherever you are, so the key is always true.
    """
    block = document_section(html).split(f"<h3>{MULTIPAGE}</h3>")[1].split("<h3>")[0]
    pages = block.split('<div data-view="pages">')[1].split('<div data-view="signals"')[0]
    assert pages.count('class="key"') == 1
    assert 'class="key"' not in pages.split("</div>\n        </div>")[0].split('class="spread"')[-1]


def test_the_workspace_is_the_same_shape_with_nothing_to_show(html):
    """A document nobody could open used to render a different block entirely.

    Switching to it resized the whole page. It gets the same bar and the same
    two frames now, with the reason inside them.
    """
    block = document_section(html).split("<h3>encrypted.pdf</h3>")[1].split("<h3>")[0]
    pages = block.split('<div data-view="pages">')[1].split('<div data-view="signals"')[0]
    assert 'class="pagebar"' in pages
    assert pages.count('class="spread"') == 1
    assert pages.count('class="side"') == 2
    assert pages.count('class="body"') == 2
    assert "No page of this document could be read" in pages


def test_nothing_to_page_through_disables_the_arrows(html):
    """A bar you can press that does nothing is worse than one you cannot."""
    block = document_section(html).split("<h3>encrypted.pdf</h3>")[1].split("<h3>")[0]
    nav = block.split('class="pnav"')[1].split("</div>")[0]
    assert nav.count("disabled") == 3, "both arrows and the number box"
    assert "/ 0" in nav


def test_why_it_could_not_be_read_is_not_only_in_the_panel(html):
    """The loader's own words belong with the measurements, not above the page."""
    block = document_section(html).split("<h3>encrypted.pdf</h3>")[1].split("<h3>")[0]
    signals = block.split('<div data-view="signals"')[1]
    assert "Reading this document was incomplete" in signals
    preamble = block.split('<div data-view="pages">')[0]
    assert "Reading this document was incomplete" not in preamble
