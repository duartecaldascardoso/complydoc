"""Reports: both formats, the generated limitations, and the no-leak guarantee."""

from __future__ import annotations

import json

import pytest

from complydoc.audit import COMPONENTS, run_audit
from complydoc.report.html_writer import render_html
from complydoc.report.json_writer import to_dict, write_json
from tests.helpers import FIXTURES

SECRETS = (
    "4111 1111 1111 1111",
    "4111111111111111",
    "AB123456C",
    "jane.doe@example.com",
    "GB82 WEST 1234 5698 7654 32",
    "GB123456782",
    "020 7946 0958",
)


@pytest.fixture(scope="module")
def report(config):
    return run_audit(FIXTURES, config, COMPONENTS, monthly_volume=1000)


@pytest.fixture(scope="module")
def html(report, config):
    return render_html(report, config)


# --- the guarantee ---------------------------------------------------------


def test_no_sensitive_value_reaches_the_html_by_default(html):
    for secret in SECRETS:
        assert secret not in html, f"{secret!r} leaked into the HTML report"


def test_no_sensitive_value_reaches_the_json_by_default(report):
    serialised = json.dumps(to_dict(report))
    for secret in SECRETS:
        assert secret not in serialised, f"{secret!r} leaked into the JSON report"


def test_reveal_is_recorded_and_stamped(config):
    revealed = run_audit(FIXTURES, config, ("sensitive",), reveal=True)
    assert revealed.run.reveal_used is True
    page = render_html(revealed, config)
    assert "unmasked sensitive values" in page
    assert any(x.area == "Masking" for x in revealed.limitations)


def test_never_reveal_categories_stay_masked_even_then(config):
    revealed = run_audit(FIXTURES, config, ("sensitive",), reveal=True)
    page = render_html(revealed, config)
    assert "4111111111111111" not in page
    assert "AB123456C" not in page


# --- self-contained --------------------------------------------------------


def test_html_has_no_external_assets(html):
    for marker in ("<script src=", "<link ", "@import", "url(http"):
        assert marker not in html, f"report pulls in an external asset: {marker}"


def test_html_carries_its_own_stylesheet(html):
    assert "<style>" in html


# --- content ---------------------------------------------------------------


def test_aggregate_section_is_present(report, html):
    assert report.aggregate is not None
    assert report.aggregate.documents_audited > 0
    assert "Summary" in html
    assert "Documents audited" in html


def test_every_document_gets_a_section(report, html):
    for document in report.documents:
        assert document.relative_path in html


def test_weights_are_printed_whenever_a_score_is(report, html):
    assert report.signal_weights, "scoring is on, so weights must be exposed"
    assert "Weight" in html
    for signal_id, weight in report.signal_weights.items():
        assert signal_id in report.aggregate.signal_distribution
        assert weight >= 0


def test_skipped_files_are_reported_not_silently_dropped(report):
    names = {s.path.name for s in report.skipped}
    assert "broken.pdf" in names
    assert "notes.txt" in names


# --- limitations -----------------------------------------------------------


def test_limitations_are_generated_from_this_run(report):
    areas = {x.area for x in report.limitations}
    assert "Files not examined" in areas
    assert "Pages that could not be read" in areas
    assert "Encrypted documents" in areas
    assert "Signals not measured" in areas


def test_limitations_name_the_documents_they_apply_to(report):
    entry = next(x for x in report.limitations if x.area == "Encrypted documents")
    assert entry.affected == ["encrypted.pdf"]


def test_running_one_component_says_so_in_the_limitations(config):
    only_sensitive = run_audit(FIXTURES, config, ("sensitive",))
    entry = next(x for x in only_sensitive.limitations if x.area == "Components not run")
    assert "cost" in entry.statement and "difficulty" in entry.statement


def test_a_run_with_everything_available_does_not_claim_missing_components(report):
    assert not any(x.area == "Components not run" for x in report.limitations)


def test_output_cost_is_declared_out_of_scope(report):
    entry = next(x for x in report.limitations if x.area == "Cost scope")
    assert "Only input cost" in entry.statement


def test_extrapolation_states_its_assumption(report):
    entry = next(x for x in report.limitations if x.area == "Volume extrapolation")
    assert entry.severity == "important"


# --- machine readable ------------------------------------------------------


def test_json_round_trips(report, tmp_path):
    path = write_json(report, tmp_path / "r.json")
    data = json.loads(path.read_text())
    assert data["run"]["schema_version"] == report.run.schema_version
    assert len(data["documents"]) == len(report.documents)
    assert "limitations" in data


def test_json_is_stable_for_diffing(report, tmp_path):
    first = write_json(report, tmp_path / "a.json").read_text()
    second = write_json(report, tmp_path / "b.json").read_text()
    assert first == second


def test_config_digest_is_recorded_so_runs_are_comparable(report, config):
    assert report.run.config_digest == config.digest


def test_offline_status_is_recorded(report):
    assert report.run.offline_guard in {"armed", "not_armed"}
