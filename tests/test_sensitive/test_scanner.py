"""End to end scanning of the synthetic PII fixture.

Every value in that fixture is fake: a published test PAN, the IBAN from the ISO
specification, an Ofcom fiction-range phone number and invented names.
"""

from __future__ import annotations

import pytest

from complydoc.sensitive.scanner import scan
from tests.helpers import requires_ner

EXPECTED_PATTERN_CATEGORIES = {
    "ni_number",
    "sort_code",
    "bank_account_number",
    "iban",
    "card_number",
    "uk_postcode",
    "street_address",
    "email_address",
    "phone_number",
    "date_of_birth",
    "vat_number",
    "utr",
}


@pytest.fixture(scope="module")
def result(loader, config):
    return scan(loader("sensitive_sample.pdf"), config.sensitive)


def test_every_configured_identifier_is_found(result):
    found = set(result.counts_by_category)
    missing = EXPECTED_PATTERN_CATEGORIES - found
    assert not missing, f"these categories were not detected: {sorted(missing)}"


def test_locations_are_reported(result):
    for match in result.matches:
        assert match.page >= 1
        assert match.line >= 1
        assert match.column >= 0


def test_no_match_carries_a_revealed_value_by_default(result):
    assert all(m.revealed is None for m in result.matches)


def test_masked_values_never_contain_the_original(loader, config):
    document = loader("sensitive_sample.pdf")
    result = scan(document, config.sensitive)
    for secret in ("4111 1111 1111 1111", "AB123456C", "GB82 WEST 1234 5698 7654 32"):
        assert all(secret not in m.masked for m in result.matches)


def test_generic_digit_runs_need_a_nearby_label(result):
    """An eight-digit account number is only reported because of its label."""
    account = next(m for m in result.matches if m.category == "bank_account_number")
    assert account.context_term is not None


def test_checksummed_categories_record_which_check_passed(result):
    card = next(m for m in result.matches if m.category == "card_number")
    assert "luhn" in card.validators_passed


def test_overlapping_identifiers_are_resolved(result):
    """A phone-shaped run inside a card number must not be double reported."""
    cards = [m for m in result.matches if m.category == "card_number"]
    assert len(cards) == 1
    card_span = range(cards[0].column, cards[0].column + cards[0].length)
    for other in result.matches:
        if other.category in {"phone_number", "utr"} and other.line == cards[0].line:
            assert other.column not in card_span


def test_reveal_produces_values_for_permitted_categories(loader, config):
    result = scan(loader("sensitive_sample.pdf"), config.sensitive, reveal=True)
    email = next(m for m in result.matches if m.category == "email_address")
    assert email.revealed == "jane.doe@example.com"


def test_reveal_is_refused_for_never_reveal_categories(loader, config):
    result = scan(loader("sensitive_sample.pdf"), config.sensitive, reveal=True)
    for match in result.matches:
        if match.category in config.sensitive.masking.never_reveal:
            assert match.revealed is None
    assert set(result.reveal_blocked_categories) == set(config.sensitive.masking.never_reveal)


def test_an_unreadable_page_is_recorded_rather_than_called_clean(loader, config):
    """Zero findings on a page nobody could read is not an all-clear."""
    result = scan(loader("scanned_page.pdf"), config.sensitive)
    assert result.total == 0
    assert result.unreadable_pages == [1]
    assert result.pages_scanned == 0


def test_a_readable_page_with_nothing_on_it_is_distinguishable(loader, config):
    result = scan(loader("two_column.pdf"), config.sensitive)
    assert result.pages_scanned == 1
    assert result.unreadable_pages == []


@requires_ner
def test_names_are_detected_when_the_model_is_installed(result):
    assert result.counts_by_category.get("person_name", 0) >= 1


@requires_ner
def test_no_entity_spans_a_line_break(result):
    for match in result.matches:
        assert "\n" not in match.masked


def test_unavailable_detectors_are_reported_as_unscanned_not_zero(loader, config):
    """The distinction that matters most in this whole component."""
    import complydoc.sensitive.detectors.ner as ner_module

    original = ner_module._load
    # Two caches sit in front of the model: the loaded pipeline and the parse of
    # the page in hand. Both have to go, or the run under test is served an
    # answer from before the model was taken away.
    ner_module._load.cache_clear()
    ner_module._parse.cache_clear()

    def unavailable(name: str):
        from complydoc.sensitive.registry import DetectorUnavailableError

        raise DetectorUnavailableError("model deliberately removed for this test")

    ner_module._load = unavailable  # type: ignore[assignment]
    try:
        result = scan(loader("sensitive_sample.pdf"), config.sensitive)
    finally:
        ner_module._load = original  # type: ignore[assignment]
        ner_module._load.cache_clear()
        ner_module._parse.cache_clear()

    assert "person_name" not in result.counts_by_category
    unscanned = {u.category for u in result.unscanned_categories}
    assert {"person_name", "organisation_name"} <= unscanned


def test_detection_is_not_tied_to_one_jurisdiction(config):
    """GDPR is not a UK-only regime, and several of these are not GDPR at all."""
    regions = {c.region for c in config.sensitive.enabled_categories.values()}
    assert len(regions) >= 6
    assert "UK" in regions and "US" in regions
    for category in config.sensitive.categories.values():
        assert "UK GDPR" not in (category.gdpr_note or "")
