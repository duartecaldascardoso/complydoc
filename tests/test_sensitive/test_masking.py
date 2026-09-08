"""Masking is the default and the point. These tests are the guard rail."""

from __future__ import annotations

import pytest

from complydoc.config.schema import MaskingConfig
from complydoc.sensitive.masking import mask_value, render, reveal_allowed

CONFIG = MaskingConfig(reveal_tail_chars=4, mask_char="*", never_reveal=["card_number"])


def test_only_the_last_four_characters_survive():
    assert mask_value("4111111111111111", CONFIG) == "************1111"


def test_separators_are_preserved_so_the_shape_stays_legible():
    assert mask_value("12-34-56", CONFIG) == "**-34-56"


def test_a_short_value_is_masked_entirely():
    """Showing four of four characters would not be masking."""
    assert mask_value("ABCD", CONFIG) == "****"
    assert mask_value("AB", CONFIG) == "**"


def test_line_breaks_never_survive_into_a_report_cell():
    """A masked value goes into a table cell and must not carry layout of its own."""
    masked = mask_value("Jane\nDoe", CONFIG)
    assert "\n" not in masked
    # Seven alphanumerics, so the last four ("eDoe") survive and the newline
    # becomes a space.
    assert masked == "***e Doe"


def test_render_masks_by_default():
    masked, revealed = render("4111111111111111", "card_number", CONFIG, reveal=False)
    assert revealed is None
    assert "4111111111111111" not in masked


def test_render_reveals_when_asked_and_permitted():
    masked, revealed = render("jane@example.com", "email_address", CONFIG, reveal=True)
    assert revealed == "jane@example.com"
    assert masked != revealed


def test_never_reveal_beats_the_reveal_flag():
    """--reveal must not be able to print a card number. Ever."""
    masked, revealed = render("4111111111111111", "card_number", CONFIG, reveal=True)
    assert revealed is None
    assert masked == "************1111"


def test_reveal_allowed_reflects_configuration():
    assert reveal_allowed("email_address", CONFIG) is True
    assert reveal_allowed("card_number", CONFIG) is False


def test_revealed_values_are_collapsed_to_one_line():
    _, revealed = render("GB82 WEST\n1234", "iban", CONFIG, reveal=True)
    assert revealed == "GB82 WEST 1234"


@pytest.mark.parametrize("tail", [0, 1, 4])
def test_tail_length_is_honoured(tail):
    config = MaskingConfig(reveal_tail_chars=tail, mask_char="*")
    masked = mask_value("ABCDEFGHIJ", config)
    assert masked.count("*") == 10 - tail
