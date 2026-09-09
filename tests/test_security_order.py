"""Ordering on the security page.

A list of findings in folder order buries the serious ones among the trivial.
The table arrives ordered by severity and can be reordered by any column.
"""

from __future__ import annotations

import pytest

from complydoc.audit import COMPONENTS, run_audit
from complydoc.report.html_writer import render_html, sensitive_rows, severity_rank
from tests.helpers import FIXTURES


@pytest.fixture(scope="module")
def report(config):
    return run_audit(FIXTURES, config, COMPONENTS)


def test_severity_ranks_by_seriousness_not_by_spelling():
    """Sorted as text, 'high' files between 'low' and 'medium'."""
    assert severity_rank("high") > severity_rank("medium") > severity_rank("low")
    assert severity_rank("anything else") == 0


def test_the_worst_findings_come_first(report):
    ranks = [severity_rank(match.severity) for _, match in sensitive_rows(report)]
    assert ranks == sorted(ranks, reverse=True)
    assert ranks[0] == severity_rank("high"), "the fixture folder holds high findings"


def test_ties_break_the_same_way_every_run(report):
    """Within one severity, order by document then position — never arbitrarily."""
    rows = sensitive_rows(report)
    high = [(d.relative_path, m.page, m.line) for d, m in rows if m.severity == "high"]
    assert high == sorted(high)


def test_every_match_survives_the_sort(report):
    counted = sum(len(d.sensitive.matches) for d in report.documents if d.sensitive)
    assert len(sensitive_rows(report)) == counted
    assert counted > 0


def test_the_columns_are_sortable(report, config):
    html = render_html(report, config)
    security = html.split('id="security"')[1].split("</section>")[0]
    assert security.count("data-sortable") == 2, "both the summary and the occurrences"
    for column in ("Document", "Category", "Severity"):
        assert f'data-sort="text">{column}' in security or f">{column}<" in security


def test_severity_sorts_on_its_rank_not_its_label(report, config):
    """The cell carries the rank, so clicking the column orders high first."""
    html = render_html(report, config)
    security = html.split('id="security"')[1].split("</section>")[0]
    assert f'data-value="{severity_rank("high")}"' in security
    assert 'data-sort-default="desc"' in security
