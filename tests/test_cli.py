"""CLI smoke tests. The components must be independently runnable."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from complydoc.cli import app
from tests.helpers import FIXTURES

runner = CliRunner()


@pytest.mark.parametrize(
    ("command", "expected_components"),
    [
        ("cost", ["cost"]),
        ("difficulty", ["difficulty"]),
        ("sensitive", ["sensitive"]),
        ("audit", ["cost", "difficulty", "sensitive"]),
    ],
)
def test_each_component_runs_on_its_own(tmp_path, command, expected_components):
    result = runner.invoke(
        app, [command, str(FIXTURES), "--out", str(tmp_path), "--name", "r", "--quiet"]
    )
    assert result.exit_code == 0, result.output
    data = json.loads((tmp_path / "r.json").read_text())
    assert data["run"]["components_run"] == expected_components


def test_sensitive_only_run_computes_no_cost(tmp_path):
    runner.invoke(
        app, ["sensitive", str(FIXTURES), "--out", str(tmp_path), "--name", "s", "--quiet"]
    )
    data = json.loads((tmp_path / "s.json").read_text())
    assert data["cost"] is None
    assert all(d["cost"] is None for d in data["documents"])
    assert data["documents"][0]["sensitive"] is not None


def test_both_formats_are_written(tmp_path):
    runner.invoke(app, ["audit", str(FIXTURES), "--out", str(tmp_path), "--name", "r", "--quiet"])
    assert (tmp_path / "r.json").is_file()
    assert (tmp_path / "r.html").is_file()


def test_monthly_volume_reaches_the_report(tmp_path):
    runner.invoke(
        app,
        [
            "cost",
            str(FIXTURES),
            "--out",
            str(tmp_path),
            "--name",
            "v",
            "--monthly-volume",
            "5000",
            "--quiet",
        ],
    )
    data = json.loads((tmp_path / "v.json").read_text())
    assert data["run"]["monthly_volume"] == 5000
    assert data["aggregate"]["annual_text_usd"] is not None


def test_reveal_defaults_to_off(tmp_path):
    runner.invoke(
        app, ["sensitive", str(FIXTURES), "--out", str(tmp_path), "--name", "d", "--quiet"]
    )
    data = json.loads((tmp_path / "d.json").read_text())
    assert data["run"]["reveal_used"] is False


def test_reveal_warns_on_stderr(tmp_path):
    result = runner.invoke(
        app,
        [
            "sensitive",
            str(FIXTURES / "sensitive_sample.pdf"),
            "--out",
            str(tmp_path),
            "--name",
            "rv",
            "--reveal",
            "--quiet",
        ],
    )
    assert result.exit_code == 0
    assert "--reveal is set" in result.output


def test_a_single_file_target_works(tmp_path):
    result = runner.invoke(
        app,
        [
            "audit",
            str(FIXTURES / "native_text.pdf"),
            "--out",
            str(tmp_path),
            "--name",
            "one",
            "--quiet",
        ],
    )
    assert result.exit_code == 0
    data = json.loads((tmp_path / "one.json").read_text())
    assert len(data["documents"]) == 1


def test_a_missing_path_exits_cleanly(tmp_path):
    result = runner.invoke(
        app, ["audit", str(tmp_path / "nope"), "--out", str(tmp_path), "--quiet"]
    )
    assert result.exit_code == 2
    assert "No such path" in result.output


def test_a_broken_config_exits_cleanly(tmp_path):
    bad = tmp_path / "cfg"
    bad.mkdir()
    (bad / "pricing.yaml").write_text("not: a: valid: mapping:")
    result = runner.invoke(
        app, ["cost", str(FIXTURES), "--config-dir", str(bad), "--out", str(tmp_path), "--quiet"]
    )
    assert result.exit_code == 2
    assert "Configuration error" in result.output


def test_doctor_reports_the_environment():
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    assert "Network guard: armed" in result.output
    assert "Price provenance" in result.output


def test_the_run_never_crashes_on_the_awkward_folder(tmp_path):
    """A folder of real documents always has something broken in it."""
    result = runner.invoke(
        app, ["audit", str(FIXTURES), "--out", str(tmp_path), "--name", "r", "--quiet"]
    )
    assert result.exit_code == 0
    data = json.loads((tmp_path / "r.json").read_text())
    assert data["aggregate"]["documents_skipped"] >= 2
    assert data["aggregate"]["documents_audited"] >= 10
