"""Model selection, and importing prices from litellm's table.

The table is stubbed rather than depending on litellm being installed — the
importer reads a JSON file, so a small fixture exercises the same path.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest
import yaml

from complydoc.config.schema import PricingConfig
from complydoc.cost.estimator import UnknownModelError, resolve_models
from complydoc.cost.pricing_import import (
    PricingImportError,
    load_table,
    select,
    to_yaml,
)

TABLE = {
    "gpt-4o": {
        "litellm_provider": "openai",
        "mode": "chat",
        "supports_vision": True,
        "input_cost_per_token": 2.5e-06,
        "output_cost_per_token": 1e-05,
    },
    "gemini/gemini-2.0-flash": {
        "litellm_provider": "gemini",
        "mode": "chat",
        "supports_vision": True,
        "input_cost_per_token": 1e-07,
        "output_cost_per_token": 4e-07,
    },
    "some-embedding-model": {
        "litellm_provider": "openai",
        "mode": "embedding",
        "input_cost_per_token": 1e-08,
    },
    "text-only-model": {
        "litellm_provider": "openai",
        "mode": "chat",
        "supports_vision": False,
        "input_cost_per_token": 5e-07,
        "output_cost_per_token": 1e-06,
    },
    "free-model": {
        "litellm_provider": "openai",
        "mode": "chat",
        "supports_vision": True,
        "input_cost_per_token": 0,
    },
    "weird-provider-model": {
        "litellm_provider": "somebody-else",
        "mode": "chat",
        "supports_vision": True,
        "input_cost_per_token": 1e-06,
        "output_cost_per_token": 2e-06,
    },
}


@pytest.fixture
def table_file(tmp_path):
    path = tmp_path / "prices.json"
    path.write_text(json.dumps(TABLE))
    return path


# --- reading the table -----------------------------------------------------


def test_loads_a_table_from_a_path(table_file):
    assert len(load_table(table_file)) == len(TABLE)


def test_a_missing_file_is_a_clear_error(tmp_path):
    with pytest.raises(PricingImportError, match="no such file"):
        load_table(tmp_path / "nope.json")


def test_non_chat_models_are_skipped():
    ids = {m.id for m in select(TABLE)}
    assert "some-embedding-model" not in ids


def test_models_with_no_price_are_skipped():
    """A price of zero is not a price."""
    assert "free-model" not in {m.id for m in select(TABLE)}


def test_vision_filter_is_the_default():
    assert "text-only-model" not in {m.id for m in select(TABLE)}


def test_naming_a_model_overrides_the_vision_filter():
    assert {m.id for m in select(TABLE, ids=["text-only-model"])} == {"text-only-model"}


def test_asking_for_an_unknown_model_fails_loudly():
    with pytest.raises(PricingImportError, match="not found"):
        select(TABLE, ids=["does-not-exist"])


def test_provider_filter():
    assert {m.id for m in select(TABLE, provider="gemini")} == {"gemini/gemini-2.0-flash"}


def test_per_token_prices_become_per_million():
    model = next(m for m in select(TABLE) if m.id == "gpt-4o")
    assert model.input_per_mtok_usd == 2.5
    assert model.output_per_mtok_usd == 10.0


def test_provider_maps_to_a_vision_formula():
    by_id = {m.id: m for m in select(TABLE)}
    assert by_id["gpt-4o"].vision_formula == "tiled_512"
    assert by_id["gemini/gemini-2.0-flash"].vision_formula == "flat_then_tiled"


def test_unknown_provider_gets_no_vision_formula():
    model = next(m for m in select(TABLE) if m.id == "weird-provider-model")
    assert model.vision_formula is None


# --- generating config -----------------------------------------------------


def test_generated_yaml_validates_against_the_real_schema(config):
    """The whole point: the output must be loadable by complydoc itself."""
    fragment = to_yaml(select(TABLE), today=dt.date(2026, 9, 8))
    base = yaml.safe_load(
        (__import__("pathlib").Path("src/complydoc/config/pricing.yaml")).read_text()
    )
    base["models"] = [m for m in base["models"] if m["enabled"]]
    base["models"] += yaml.safe_load("models:\n" + fragment)["models"]

    parsed = PricingConfig.model_validate(base)
    ids = {m.id for m in parsed.usable_models}
    assert {"gpt-4o", "gemini/gemini-2.0-flash"} <= ids


def test_import_stamps_the_date_it_was_run():
    fragment = to_yaml(select(TABLE), today=dt.date(2026, 9, 8))
    assert "last_verified: 2026-09-08" in fragment
    assert "litellm" in fragment


def test_openai_tokenizer_is_marked_exact_and_others_approximate():
    fragment = yaml.safe_load("models:\n" + to_yaml(select(TABLE)))["models"]
    by_id = {m["id"]: m for m in fragment}
    assert by_id["gpt-4o"]["tokenizer"]["fidelity"] == "exact"
    assert by_id["gemini/gemini-2.0-flash"]["tokenizer"]["fidelity"] == "approximate"


# --- selecting models to price --------------------------------------------


def test_no_selection_prices_every_enabled_model(config):
    assert resolve_models(config.pricing, None) == config.pricing.usable_models


def test_selection_narrows_the_comparison(config):
    chosen = resolve_models(config.pricing, ["claude-haiku-4-5"])
    assert [m.id for m in chosen] == ["claude-haiku-4-5"]


def test_selecting_an_unknown_model_is_an_error(config):
    with pytest.raises(UnknownModelError, match=r"not in pricing\.yaml"):
        resolve_models(config.pricing, ["no-such-model"])


def test_selecting_an_unpriced_template_is_an_error(config):
    """A model present in the config but carrying no price cannot be costed."""
    raw = config.pricing.model_dump()
    raw["models"].append(
        {
            "id": "priceless",
            "provider": "nobody",
            "display_name": "Priceless",
            "enabled": True,
            "input_per_mtok_usd": None,
            "output_per_mtok_usd": None,
            "supports_vision": False,
            "vision_formula": None,
            "tokenizer": {"encoding": "o200k_base", "fidelity": "exact"},
            "last_verified": None,
            "source_url": None,
            "notes": None,
        }
    )
    pricing = PricingConfig.model_validate(raw)
    with pytest.raises(UnknownModelError, match="no price"):
        resolve_models(pricing, ["priceless"])
