"""Text out of documents, with the identifiers covered over.

The audit says what a folder is like. This hands back the folder's own words,
ready to be sent somewhere else, and that makes the promises harder: a caller
is about to put this in front of a model on the strength of what it says.

So the line these tests hold is that nothing here overclaims. The text is
whole, the token counts say how good they are, and what could not be read — or
could not be masked — is said out loud rather than left to be noticed.
"""

from __future__ import annotations

import complydoc as cd
from complydoc.extract import (
    MASKING_BEST_EFFORT,
    MASKING_INCOMPLETE,
    UNREADABLE_DOCUMENT,
    UNREADABLE_PAGE,
)
from tests.helpers import FIXTURES, requires_ner

SENSITIVE = FIXTURES / "sensitive_sample.pdf"


def kinds(result: cd.TextResult) -> set[str]:
    return {w.kind for w in result.warnings}


def test_the_identifiers_are_covered_over():
    result = cd.extract_text(SENSITIVE, ocr=False)
    assert result.masked_count > 0
    assert "•" in result.text
    assert "4111 1111 1111 1111" not in result.text, "the card number is not in the clear"
    assert "AB123456C" not in result.text


def test_nothing_is_masked_when_nothing_is_asked_for():
    """`mask=False` runs no scan at all, and says the text is not masked."""
    raw = cd.extract_text(SENSITIVE, ocr=False, mask=False)
    assert not raw.masked
    assert raw.masked_count == 0
    assert "4111 1111 1111 1111" in raw.text


def test_the_text_is_not_truncated_the_way_the_report_truncates_it():
    """The report cuts a page at twenty thousand characters, for a reader.

    Dropping the end of a contract without saying so would be indefensible
    here, which is why this loads documents directly instead of reading the
    text back off a report.
    """
    from complydoc.audit import _MAX_TEXT_CHARS

    long_page = FIXTURES / "dense_text.pdf"
    result = cd.extract_text(long_page, ocr=False, mask=False)
    characters = sum(len(c.text) for c in result.chunks)
    assert characters > 0

    # The fixture is shorter than the cap, so assert the mechanism instead of
    # shipping a 20,000-character fixture to prove it.
    report = cd.full_audit(long_page, extracted_text=True)
    assert report.documents[0].extracted_text[0].text == result.chunks[0].text[:_MAX_TEXT_CHARS]


def test_every_chunk_says_how_good_its_token_count_is():
    result = cd.extract_text(SENSITIVE, ocr=False)
    assert result.chunks
    for chunk in result.chunks:
        assert chunk.tokens > 0
        assert chunk.token_fidelity in {"exact", "approximate", "estimated"}
        assert chunk.encoding


def test_the_total_is_the_sum_of_the_chunks():
    result = cd.extract_text(SENSITIVE, ocr=False)
    assert result.tokens == sum(c.tokens for c in result.chunks)


def test_a_page_nothing_could_be_read_off_is_reported_not_dropped():
    """A silently missing page is the failure this exists to prevent."""
    result = cd.extract_text(FIXTURES / "scanned_page.pdf", ocr=False)
    assert UNREADABLE_PAGE in kinds(result)
    assert not result.complete
    gap = next(w for w in result.warnings if w.kind == UNREADABLE_PAGE)
    assert gap.page == 1
    assert "OCR was not run" in gap.detail


def test_a_file_that_would_not_open_is_reported():
    result = cd.extract_text(FIXTURES, ocr=False, recurse=False)
    assert UNREADABLE_DOCUMENT in kinds(result)
    assert not result.complete
    assert result.documents_skipped > 0


@requires_ner
def test_masking_is_always_declared_best_effort():
    """The warning that matters most, and it is true every time.

    A card number is masked because it passed a checksum. A person's name is
    masked because a model thought it was one, and models miss — on the sample
    document the model finds "John Smith" and misses "Jane Doe" above it.
    """
    result = cd.extract_text(SENSITIVE, ocr=False)
    assert MASKING_BEST_EFFORT in kinds(result)
    warning = next(w for w in result.warnings if w.kind == MASKING_BEST_EFFORT)
    assert "missed" in warning.detail


def test_no_best_effort_warning_when_nothing_was_masked():
    assert MASKING_BEST_EFFORT not in kinds(cd.extract_text(SENSITIVE, ocr=False, mask=False))


@requires_ner
def test_a_chunk_separates_what_was_confirmed_from_what_was_guessed():
    """The part of the masking that rests on a model, in a number."""
    result = cd.extract_text(SENSITIVE, ocr=False)
    chunk = next(c for c in result.chunks if c.masked)
    assert chunk.masked_confirmed <= chunk.masked
    assert chunk.masked_confirmed < chunk.masked, "the fixture carries names as well"


def test_a_category_that_could_not_run_is_not_silently_unmasked(monkeypatch):
    """Without the model, names are not masked — and that has to be said.

    Anything else means a caller sends text they believe is clean because the
    thing that would have found the names never ran.
    """
    from complydoc.sensitive.detectors import ner

    def unavailable(_name: str) -> object:
        raise ner.DetectorUnavailableError("the model is not installed")

    monkeypatch.setattr(ner, "_load", unavailable)
    monkeypatch.setattr(ner, "_parse", unavailable)

    result = cd.extract_text(SENSITIVE, ocr=False)
    assert MASKING_INCOMPLETE in kinds(result)
    assert not result.all_categories_scanned
    detail = next(w for w in result.warnings if w.kind == MASKING_INCOMPLETE).detail
    assert "may still carry" in detail


def test_a_page_is_split_to_fit_a_token_budget():
    result = cd.extract_text(FIXTURES / "dense_text.pdf", ocr=False, max_tokens=200)
    assert len(result.chunks) > 1, "the fixture is longer than the budget"
    assert all(c.document == "dense_text.pdf" for c in result.chunks)
    assert [c.part for c in result.chunks] == list(range(1, len(result.chunks) + 1))
    # Generous, because a paragraph longer than the budget is passed through
    # whole rather than cut mid-sentence.
    assert all(c.tokens <= 200 * 2 for c in result.chunks)


def test_a_path_that_is_not_there_raises():
    import pytest

    with pytest.raises(FileNotFoundError):
        cd.extract_text("no-such-folder-anywhere")


def test_a_loader_somebody_else_wrote_is_used_like_our_own(tmp_path):
    """The plug-in point, exercised through the public names only."""
    note = tmp_path / "note.complytest"
    note.write_text("Card 4111 1111 1111 1111\n", encoding="utf-8")

    class Loader:
        extensions = (".complytest",)
        format = cd.DocumentFormat.OTHER

        def load(self, path, options):
            document = cd.Document(path=path, sha256=cd.sha256_of(path), format=self.format)
            page = cd.Page(number=1, width_pt=595.0, height_pt=842.0)
            page.text = path.read_text(encoding="utf-8")
            page.text_source = "native"
            document.pages.append(page)
            return document

    assert ".complytest" not in cd.supported_extensions()
    cd.register_loader(Loader())
    assert ".complytest" in cd.supported_extensions()

    result = cd.extract_text(tmp_path, ocr=False)
    assert result.masked_count >= 1, "the scan ran over the text our loader returned"
    assert "4111 1111 1111 1111" not in result.text


def test_an_overlapping_weaker_match_cannot_expose_a_confirmed_one(tmp_path):
    """The bug this was written to close.

    The detectors are independent, so a card number that passed a checksum and
    a name a model thought it saw can claim the same characters. On a line
    reading `Card 4111 1111 1111 1111` the model calls `Card 4111` an
    organisation. Replacing one after the other let the weaker write back over
    the stronger and put four digits of a card number in the clear.
    """
    note = tmp_path / "overlap.complyoverlap"
    note.write_text("Card 4111 1111 1111 1111\n", encoding="utf-8")

    class Loader:
        extensions = (".complyoverlap",)
        format = cd.DocumentFormat.OTHER

        def load(self, path, options):
            document = cd.Document(path=path, sha256=cd.sha256_of(path), format=self.format)
            page = cd.Page(number=1, width_pt=595.0, height_pt=842.0)
            page.text = path.read_text(encoding="utf-8")
            page.text_source = "native"
            document.pages.append(page)
            return document

    cd.register_loader(Loader())
    text = cd.extract_text(tmp_path, ocr=False).text

    assert "4111 1111 1111" not in text, "the card number must not survive in any part"
    # Only the last four of an identifier are ever shown, so exactly one "1111".
    assert text.count("1111") == 1, text


def test_the_strongest_evidence_claims_the_characters(tmp_path):
    """Where two matches want the same span, the checksum-backed one wins."""
    from complydoc.extract import _mask_page
    from complydoc.sensitive.base import SensitiveMatch

    def match(column, length, masked, evidence):
        return SensitiveMatch(
            category="c",
            label="l",
            severity="high",
            page=1,
            line=1,
            column=column,
            length=length,
            masked=masked,
            evidence=evidence,
        )

    # A model's guess arrives first in position but second in strength.
    text, replaced, confirmed = _mask_page(
        "AB 4111111111111111",
        [
            match(0, 7, "•• ••11", "model"),
            match(3, 16, "••••••••••••1111", "confirmed"),
        ],
    )
    assert text.endswith("1111")
    assert "4111" not in text
    assert (replaced, confirmed) == (2, 1)
