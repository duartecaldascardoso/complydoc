"""CLI smoke tests. The components must be independently runnable."""

from __future__ import annotations

import json
import pathlib

import pytest
from typer.testing import CliRunner

from complydoc.cli import app
from tests.helpers import FIXTURES

runner = CliRunner()


@pytest.mark.parametrize(
    ("command", "expected_components"),
    [
        ("cost", ["cost"]),
        ("readiness", ["readiness"]),
        ("sensitive", ["sensitive"]),
        ("audit", ["cost", "readiness", "sensitive"]),
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


def test_models_command_lists_configured_models(monkeypatch):
    """Read at a fixed width: a narrow terminal wraps the ids mid-string.

    The table is for a person to read, so the test reads it the way a person
    with a normal-sized window would rather than at whatever width happens to
    be running the suite.
    """
    # The console is built when the module is imported, so it has already read
    # the width; setting the environment here would be too late.
    from complydoc import cli

    monkeypatch.setattr(cli.console, "width", 200)
    result = runner.invoke(app, ["models"])
    assert result.exit_code == 0
    assert "claude-opus-5" in result.output
    assert "verified" in result.output, "the table says where each price came from"


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
    assert 'class="spread"' in html, "a page sits beside what was read off it"
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


def _run_json(tmp_path, *flags):
    import json

    runner.invoke(
        app,
        [
            "audit",
            str(FIXTURES / "native_text.pdf"),
            "--out",
            str(tmp_path),
            "--name",
            "t",
            "--quiet",
            "--no-ocr",
            *flags,
        ],
    )
    return json.loads((tmp_path / "t.json").read_text())


def test_the_extracted_text_is_kept_by_default(tmp_path):
    """Reading a page beside what was read off it is the point of the tool.

    Asserted through the CLI rather than by reading the help text, which wraps at
    the width of whatever terminal is running the test, or by introspecting
    typer, whose internals are not the contract.
    """
    report = _run_json(tmp_path)
    assert report["run"]["extracted_text_used"] is True
    assert report["documents"][0]["extracted_text"]


def test_the_text_can_be_left_out(tmp_path):
    report = _run_json(tmp_path, "--no-extracted-text")
    assert report["run"]["extracted_text_used"] is False
    assert not report["documents"][0].get("extracted_text")


def test_models_can_be_listed_newest_first(monkeypatch):
    """An alphabetical dump sorts a two-year-old model above this month's.

    Checked against the catalogue rather than by reading dates out of the
    table, which prints release dates and import dates in the same row.
    """
    from complydoc import cli
    from complydoc.config.loader import load_config
    from complydoc.cost.price_table import released_on

    dated = [(released_on(m.id), m.id) for m in load_config().pricing.models]
    latest = max(date for date, _ in dated if date)
    expected = {model_id for date, model_id in dated if date == latest}

    monkeypatch.setattr(cli.console, "width", 200)
    result = runner.invoke(app, ["models", "--new", "5"])
    assert result.exit_code == 0
    assert "Released" in result.output
    assert any(model_id in result.output for model_id in expected), (
        "the most recently released model should be in the newest five"
    )


def test_searching_the_catalogue_finds_imported_models(monkeypatch):
    from complydoc import cli

    monkeypatch.setattr(cli.console, "width", 200)
    result = runner.invoke(app, ["models", "gemini"])
    assert result.exit_code == 0
    assert "imported" in result.output


def test_the_demo_audits_the_samples_that_ship_with_the_tool(tmp_path):
    """Somebody evaluating this should not have to find a folder first."""
    import json

    result = runner.invoke(app, ["demo", "--no-open", "--no-ocr", "--out", str(tmp_path)])
    assert result.exit_code == 0, result.output
    report = json.loads((tmp_path / "complydoc-demo.json").read_text())
    assert len(report["documents"]) == 6


def test_the_sample_folder_holds_documents_and_nothing_else():
    """Discovery reports anything else as a skipped file, and the demo is the
    first thing many people see."""
    from importlib.resources import files

    from complydoc.ingest.registry import supported_extensions

    allowed = set(supported_extensions())
    folder = files("complydoc.sample")
    names = [entry.name for entry in folder.iterdir() if entry.is_file()]
    assert names, "the samples ship with the package"
    assert all(pathlib.PurePath(name).suffix.lower() in allowed for name in names), names
