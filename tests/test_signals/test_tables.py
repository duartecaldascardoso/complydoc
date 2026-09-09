"""Table detection, including the tables that carry no ruling lines.

Most invoices align their columns with whitespace and draw no rules at all. The
line-based pass finds nothing in them, and running a text-alignment pass on its
own is worse than useless: it finds a thirteen-column table in a page of prose.
These tests pin both halves — the tables it must find and the prose it must not.
"""

from __future__ import annotations

import pytest

from complydoc.readiness.analyser import analyse
from complydoc.readiness.base import SignalStatus

PROSE = [
    "dense_text.pdf",
    "two_column.pdf",
    "native_text.pdf",
    "sensitive_sample.pdf",
    "garbled.pdf",
    "acroform.pdf",
    "mixed_page_sizes.pdf",
]


def test_a_whitespace_aligned_table_is_found(loader):
    document = loader("whitespace_table.pdf")
    tables = [t for p in document.pages for t in p.tables]
    assert len(tables) == 1
    assert tables[0].detected_by == "alignment"
    assert tables[0].cols == 4
    assert tables[0].rows >= 5


def test_a_ruled_table_is_still_found_by_its_rules(loader):
    document = loader("merged_header_table.pdf")
    tables = [t for p in document.pages for t in p.tables]
    assert len(tables) == 1
    assert tables[0].detected_by == "lines"


@pytest.mark.parametrize("name", PROSE)
def test_prose_is_never_mistaken_for_a_table(loader, name):
    """A column boundary that cuts through words is not a column."""
    document = loader(name)
    assert [t for p in document.pages for t in p.tables] == []


def test_alignment_tables_do_not_claim_a_header_depth(loader, config):
    document = loader("whitespace_table.pdf")
    result = analyse(document, config.readiness)
    for signal_id in ("table_max_header_depth", "table_merged_cells"):
        signal = next(s for s in result.signals if s.id == signal_id)
        assert signal.status is SignalStatus.NOT_APPLICABLE
        assert "ruling lines" in (signal.reason or "") or "spans" in (signal.reason or "")


def test_the_count_says_how_each_table_was_found(loader, config):
    document = loader("whitespace_table.pdf")
    signal = next(s for s in analyse(document, config.readiness).signals if s.id == "table_count")
    assert signal.detail["aligned_tables"] == 1
    assert signal.detail["ruled_tables"] == 0
