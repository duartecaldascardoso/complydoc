"""Checksums. These are what stop the scan drowning in false positives."""

from __future__ import annotations

import pytest

from complydoc.sensitive.validators import (
    iban_mod97,
    luhn,
    ni_prefix,
    plausible_dob,
    sort_code,
    uk_phone,
    uk_postcode,
    validate,
    vat_mod97,
)


@pytest.mark.parametrize("value", ["4111 1111 1111 1111", "4111111111111111", "5500005555555559"])
def test_luhn_accepts_valid_test_pans(value):
    assert luhn(value) is True


@pytest.mark.parametrize("value", ["4111111111111112", "1234567812345678", "123"])
def test_luhn_rejects_invalid(value):
    assert luhn(value) is False


def test_iban_accepts_the_specification_example():
    assert iban_mod97("GB82 WEST 1234 5698 7654 32") is True


@pytest.mark.parametrize("value", ["GB83 WEST 1234 5698 7654 32", "GB82WEST", "not an iban"])
def test_iban_rejects_invalid(value):
    assert iban_mod97(value) is False


@pytest.mark.parametrize("value", ["AB123456C", "JK 12 34 56 A"])
def test_ni_prefix_accepts_valid(value):
    assert ni_prefix(value) is True


@pytest.mark.parametrize(
    ("value", "why"),
    [
        ("QQ123456C", "Q is not allowed"),
        ("DA123456C", "D is not allowed first"),
        ("BG123456C", "administratively reserved pair"),
    ],
)
def test_ni_prefix_rejects_invalid(value, why):
    assert ni_prefix(value) is False, why


def test_vat_accepts_a_checksum_valid_number():
    assert vat_mod97("GB123456782") is True


def test_vat_rejects_a_checksum_invalid_number():
    assert vat_mod97("GB123456789") is False


@pytest.mark.parametrize(("value", "expected"), [("12-34-56", True), ("000000", False)])
def test_sort_code(value, expected):
    assert sort_code(value) is expected


@pytest.mark.parametrize(
    ("value", "expected"), [("EC1A 1BB", True), ("SW1A2AA", True), ("ZZ9 9ZZ", False)]
)
def test_uk_postcode(value, expected):
    assert uk_postcode(value) is expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [("020 7946 0958", True), ("+44 20 7946 0958", True), ("123", False), ("99999999999", False)],
)
def test_uk_phone(value, expected):
    assert uk_phone(value) is expected


def test_dob_rejects_an_implausible_year():
    assert plausible_dob("14/03/1985") is True
    assert plausible_dob("14/03/1785") is False


def test_validate_stops_at_the_first_failure():
    ok, passed = validate("not a card", ["luhn", "iban_mod97"])
    assert ok is False
    assert passed == []


def test_validate_reports_which_checks_passed():
    ok, passed = validate("GB82 WEST 1234 5698 7654 32", ["iban_mod97"])
    assert ok is True
    assert passed == ["iban_mod97"]


def test_unknown_validator_name_is_ignored_not_fatal():
    ok, passed = validate("anything", ["no_such_validator"])
    assert ok is True
    assert passed == []


# --- other jurisdictions ---------------------------------------------------


@pytest.mark.parametrize(
    ("checker", "good", "bad"),
    [
        ("us_ssn", "219-09-9999", "666-12-3456"),
        ("us_ssn", "219-09-9999", "000-12-3456"),
        ("aba_routing", "111000025", "111000026"),
        ("nl_bsn", "111222333", "111222334"),
        ("pt_nif", "501442600", "501442601"),
        ("es_dni", "12345678Z", "12345678A"),
        ("es_dni", "X1234567L", "X1234567A"),
        ("ie_pps", "1234567FA", "1234567XX"),
        ("de_steuer_id", "02476291358", "02476291359"),
    ],
)
def test_national_identifier_checksums(checker, good, bad):
    """Each of these carries a checksum, which is what keeps the scan usable."""
    from complydoc.sensitive.validators import VALIDATORS

    assert VALIDATORS[checker](good) is True, f"{checker} rejected a valid value"
    assert VALIDATORS[checker](bad) is False, f"{checker} accepted an invalid value"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("DE123456789", True),
        ("GB123456782", True),
        ("GB123456789", False),
        ("NL123456789B01", True),
        ("XX123", False),
        ("FR1234567890", False),
    ],
)
def test_eu_vat_country_rules(value, expected):
    from complydoc.sensitive.validators import eu_vat

    assert eu_vat(value) is expected


def test_every_configured_validator_exists(config):
    """A typo in the config would otherwise silently disable a checksum."""
    from complydoc.sensitive.validators import VALIDATORS

    for name, category in config.sensitive.categories.items():
        for validator in category.validators:
            assert validator in VALIDATORS, f"{name} names unknown validator {validator!r}"


def test_categories_cover_more_than_one_jurisdiction(config):
    regions = {c.region for c in config.sensitive.enabled_categories.values()}
    assert {"UK", "US", "international"} <= regions
    assert len(regions) >= 6
