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


def test_models_command_lists_configured_models():
    result = runner.invoke(app, ["models"])
    assert result.exit_code == 0
    assert "claude-opus-5" in result.output
    assert "width_height_area" in result.output


def test_model_selection_narrows_the_report(tmp_path):
    result = runner.invoke(
        app,
        [
            "cost",
            str(FIXTURES),
            "--model",
            "claude-haiku-4-5",
            "--out",
            str(tmp_path),
            "--name",
            "one",
            "--quiet",
        ],
    )
    assert result.exit_code == 0, result.output
    data = json.loads((tmp_path / "one.json").read_text())
    for document in data["documents"]:
        assert [m["model_id"] for m in document["cost"]["models"]] == ["claude-haiku-4-5"]


def test_repeating_the_flag_compares_several(tmp_path):
    result = runner.invoke(
        app,
        [
            "cost",
            str(FIXTURES / "native_text.pdf"),
            "-m",
            "claude-opus-5",
            "-m",
            "claude-haiku-4-5",
            "--out",
            str(tmp_path),
            "--name",
            "two",
            "--quiet",
        ],
    )
    assert result.exit_code == 0, result.output
    data = json.loads((tmp_path / "two.json").read_text())
    assert [m["model_id"] for m in data["documents"][0]["cost"]["models"]] == [
        "claude-opus-5",
        "claude-haiku-4-5",
    ]


def test_unknown_model_exits_cleanly(tmp_path):
    result = runner.invoke(
        app, ["cost", str(FIXTURES), "--model", "nope", "--out", str(tmp_path), "--quiet"]
    )
    assert result.exit_code == 2
    assert "Unknown model" in result.output


def test_pricing_import_needs_a_selection():
    result = runner.invoke(app, ["pricing-import"])
    assert result.exit_code == 2
    assert "Nothing selected" in result.output


def test_pricing_import_emits_valid_yaml(tmp_path):
    import yaml

    table = tmp_path / "prices.json"
    table.write_text(
        json.dumps(
            {
                "gpt-4o": {
                    "litellm_provider": "openai",
                    "mode": "chat",
                    "supports_vision": True,
                    "input_cost_per_token": 2.5e-06,
                    "output_cost_per_token": 1e-05,
                },
            }
        )
    )
    result = runner.invoke(app, ["pricing-import", "--from", str(table), "-m", "gpt-4o"])
    assert result.exit_code == 0, result.output
    parsed = yaml.safe_load("models:\n" + result.stdout)["models"]
    assert parsed[0]["id"] == "gpt-4o"
    assert parsed[0]["input_per_mtok_usd"] == 2.5


def test_page_previews_reach_the_html(tmp_path):
    runner.invoke(
        app,
        [
            "audit",
            str(FIXTURES / "sensitive_sample.pdf"),
            "--out",
            str(tmp_path),
            "--name",
            "pv",
            "--quiet",
        ],
    )
    html = (tmp_path / "pv.html").read_text()
    assert 'class="pv"' in html, "the page wireframe should be in the report"
    assert 'class="pair"' in html, "wireframes sit in a document/extraction pair"
    assert "<text" not in html.split('class="pv"')[1].split("</svg>")[0]


def test_skill_prints_valid_frontmatter():
    result = runner.invoke(app, ["skill"])
    assert result.exit_code == 0
    assert result.output.lstrip().startswith("---")
    assert "name: complydoc" in result.output
    assert "description:" in result.output


def test_skill_installs_where_asked(tmp_path):
    result = runner.invoke(app, ["skill", "--install", "--to", str(tmp_path)])
    assert result.exit_code == 0
    written = tmp_path / "complydoc" / "SKILL.md"
    assert written.is_file()
    assert "complydoc" in written.read_text()


def test_skill_ships_inside_the_package():
    """One install has to give you the tool and the instructions for driving it."""
    from importlib.resources import files

    assert files("complydoc.skill").joinpath("SKILL.md").is_file()
